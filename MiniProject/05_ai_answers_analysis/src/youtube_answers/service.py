import asyncio
from dataclasses import dataclass, field

from youtube_backend.schemas import (
    AnalysisRequest,
    AnswerResult,
    ChatRequest,
    Citation,
    Coverage,
    Evidence,
    ProviderMetadata,
    Source,
)
from youtube_backend.urls import canonical_url

from .authorization import MemberContext, guard_context
from .models import GeneratedAnswer, error
from .prompts import input_size, json_text, payload
from .transcript import has_performer_cues, wants_performer_attribution, wants_transcript


@dataclass
class Run:
    sources: list[Source]
    context: object
    records: dict = field(default_factory=dict)
    processed: set = field(default_factory=set)
    notes: list = field(default_factory=list)
    calls: int = 0
    metadata: list = field(default_factory=list)


class AnswerService:
    """Knowledge boundary: inventory/search/read/evidence, using 02's execution context."""

    def __init__(self, settings, model, knowledge):
        self.settings, self.model, self.knowledge = settings, model, knowledge

    def _run(self, sources, context, kinds):
        context.check()
        sources = [Source.model_validate(s).model_copy(deep=True) for s in sources]
        if not sources or len({s.video_id for s in sources}) != len(sources):
            raise error("invalid_scope", "Provide distinct authorized sources", status=422)
        context = guard_context(context, sources, kinds)
        return Run(sources, context)

    def _request(self, schema, request, run):
        request = schema.model_validate(request).model_dump(mode="json")
        authorized = {s.video_id for s in run.sources}
        if not authorized.issubset(request["scope"]["video_ids"]):
            raise error("invalid_scope", "Request and authorized source IDs differ", status=422)
        # Channel/date/ownership filters were resolved by 02 when freezing Source records.
        request["scope"]["video_ids"] = [s.video_id for s in run.sources]
        return request

    async def _bounded(self, run, function):
        run.context.check()
        timeout = min(self.settings.llm_timeout_seconds, run.context.remaining_seconds)
        try:
            async with asyncio.timeout(timeout):
                result = await function(timeout)
        except TimeoutError:
            raise error(
                "generation_timeout",
                "Answer operation exceeded its deadline",
                status=504,
                retryable=True,
            ) from None
        run.context.check()
        return result

    def _record(self, run, value):
        record = Evidence.model_validate(value)
        source = next((s for s in run.sources if s.video_id == record.video_id), None)
        if source is None or record.transcript_version != source.transcript_version:
            raise error("invalid_scope", "Evidence exceeds authorized source versions")
        previous = run.records.get(record.chunk_id)
        if previous is not None and previous != record:
            raise error("source_changed", "Evidence changed during the operation")
        run.records[record.chunk_id] = record
        if len(run.records) > self.settings.answer_max_chunks:
            raise error("analysis_budget_exceeded", "Selected evidence exceeds chunk limit")
        return {
            "text": record.text,
            "video_id": record.video_id,
            "title": record.title,
            "citation_ids": [record.chunk_id],
        }

    async def _generate(self, run, data):
        if input_size(data) > self.settings.max_context_tokens:
            raise error("context_budget_exceeded", "Input exceeds conservative context guard")
        if run.calls >= self.settings.answer_max_model_calls:
            raise error("analysis_budget_exceeded", "Answer model call budget exhausted")
        run.calls += 1
        generated = await self._bounded(run, lambda timeout: self.model.generate(data, timeout))
        try:
            result = GeneratedAnswer.model_validate(generated.content)
            metadata = ProviderMetadata.model_validate(generated.metadata)
        except (ValueError, TypeError):
            raise error("invalid_model_output", "Model returned an invalid answer") from None
        allowed = {cid for item in data["untrusted_evidence"] for cid in item["citation_ids"]}
        for statement in result.statements:
            if set(statement.citation_ids) - allowed:
                raise error("invalid_citation", "Model cited evidence absent from this request")
        run.metadata.append(metadata)
        return result

    def _history(self, history, run):
        selected = []
        size = 0
        for item in reversed(history):
            if item.get("role") not in {"user", "assistant"}:
                continue
            content = item.get("content")
            if not isinstance(content, str):
                continue
            entry = {"role": item["role"], "content": content}
            entry_size = len(json_text(entry).encode("utf-8"))
            if (
                len(selected) >= self.settings.answer_max_history_messages
                or size + entry_size > self.settings.answer_max_history_bytes
            ):
                break
            selected.append(entry)
            size += entry_size
        if len(selected) != len(history):
            run.notes.append("Conversation history was limited to recent messages within budget.")
        return list(reversed(selected))

    async def answer(self, request, sources, history, context):
        run = self._run(sources, context, {"chat"})
        request = self._request(ChatRequest, request, run)
        if isinstance(run.context, MemberContext):
            run.context.conversation(request.get("conversation_id"))
            history = run.context.history(history)
        if wants_performer_attribution(request["question"]):
            return await self._performer_attribution(run, request)
        if wants_transcript(request["question"]):
            return await self._transcript(run)
        history = self._history(history, run)
        # Carry recent user context into retrieval without asking a model to change scope.
        query = request["question"]
        for item in reversed(history):
            candidate = item["content"] + "\n" + query
            if item["role"] == "user" and len(candidate.encode("utf-8")) <= 6500:
                query = candidate
        expected = await self._bounded(
            run, lambda _: self.knowledge.inventory(run.sources, run.context)
        )
        hits = await self._bounded(
            run,
            lambda _: self.knowledge.search(
                query, run.sources, run.context, top_k=self.settings.retrieval_top_k
            ),
        )
        nodes = [self._record(run, hit.chunk.evidence()) for hit in hits]
        data = payload("answer", request, nodes, history)
        while nodes and input_size(data) > self.settings.max_context_tokens:
            nodes.pop()
            data = payload("answer", request, nodes, history)
            if "Retrieved evidence was limited to fit the input budget." not in run.notes:
                run.notes.append("Retrieved evidence was limited to fit the input budget.")
        if hits and not nodes:
            raise error("context_budget_exceeded", "Question/history/evidence exceeds input budget")
        if nodes:
            output = await self._generate(run, data)
            run.processed.update(cid for node in nodes for cid in node["citation_ids"])
        else:
            output = GeneratedAnswer(
                status="insufficient_evidence", message="ไม่พบหลักฐานที่เพียงพอในวิดีโอที่เลือก"
            )
        run.notes.append("Question answering uses ranked retrieval, not whole-video analysis.")
        return await self._finish(run, output, expected, full=False)

    def _groups(self, task, request, nodes):
        groups, current = [], []
        for node in nodes:
            if (
                input_size(payload(task, request, [*current, node]))
                > self.settings.max_context_tokens
            ):
                if not current:
                    raise error("context_budget_exceeded", "A single evidence item exceeds budget")
                groups.append(current)
                current = []
            current.append(node)
            if input_size(payload(task, request, current)) > self.settings.max_context_tokens:
                raise error("context_budget_exceeded", "A single evidence item exceeds budget")
        if current:
            groups.append(current)
        return groups

    async def _read_all(self, run):
        chunks, cursors, cursor, expected, snapshot = [], set(), None, None, None
        while True:
            page = await self._bounded(
                run,
                lambda _, cursor=cursor: self.knowledge.read(
                    run.sources,
                    run.context,
                    limit=self.settings.answer_read_page_size,
                    cursor=cursor,
                ),
            )
            signature = (page.total, page.inventory.model_dump_json())
            if snapshot is not None and signature != snapshot:
                raise error("source_changed", "Chunk inventory changed during analysis")
            snapshot = signature
            expected = page.inventory.expected_chunks
            for chunk in page.items:
                if chunk.chunk_id in run.records:
                    raise error(
                        "invalid_inventory", "Chunk enumeration returned duplicate evidence"
                    )
                self._record(run, chunk.evidence())
                chunks.append(chunk)
            if page.next_cursor is None:
                if len(chunks) != page.total:
                    raise error("invalid_inventory", "Chunk enumeration is incomplete")
                break
            if page.next_cursor in cursors or not page.items:
                raise error("invalid_inventory", "Chunk pagination did not advance")
            cursors.add(page.next_cursor)
            cursor = page.next_cursor
        if not page.inventory.complete:
            run.notes.append("Some selected videos have no available index; coverage is partial.")
        return chunks, expected

    async def _transcript(self, run):
        chunks, expected = await self._read_all(run)
        statements, size = [], 0
        for source in run.sources:
            selected = [chunk for chunk in chunks if chunk.video_id == source.video_id]
            if not selected:
                continue
            segments = await self._bounded(
                run, lambda _, source=source: self.knowledge.transcript(source, run.context)
            )
            refs = {}
            for chunk in selected:
                for segment_id in chunk.segment_ids:
                    refs.setdefault(segment_id, []).append(chunk.chunk_id)
            if set(refs) != {segment.segment_id for segment in segments}:
                raise error("source_changed", "Transcript and indexed segment inventory differ")
            # Use original segments once in stored order, preserving repeated verses.
            # Overlapping/split RAG chunks are citation anchors, not display text.
            text, citations = "", []
            for segment in segments:
                size += len(segment.text.encode("utf-8"))
                if size > 1000000 or len(segment.text) > 11000:
                    raise error("transcript_too_large", "Transcript exceeds the display budget")
                if text and len(text) + len(segment.text) + 1 > 11000:
                    statements.append(
                        {"text": text, "citation_ids": list(dict.fromkeys(citations))}
                    )
                    text, citations = "", []
                text += ("\n" if text else "") + segment.text
                citations.extend(refs[segment.segment_id])
            if text:
                statements.append({"text": text, "citation_ids": list(dict.fromkeys(citations))})
            if (
                len(statements) > 100
                or len({cid for statement in statements for cid in statement["citation_ids"]})
                > 1000
            ):
                raise error("transcript_too_large", "Transcript exceeds the display budget")
        run.processed.update(run.records)
        run.notes.append(
            "แสดงบทถอดเสียงทั้งหมดที่นำเข้าได้ตามลำดับเดิม คำบรรยายอัตโนมัติอาจคลาดเคลื่อนหรือขาดบางช่วงจากเสียงจริง"
        )
        output = GeneratedAnswer(
            status="answered" if statements else "insufficient_evidence",
            statements=statements,
            message="" if statements else "ไม่พบบทถอดเสียงที่พร้อมแสดงในคลิปที่เลือก",
        )
        result = await self._finish(run, output, expected, full=True)
        result.provider_metadata = ProviderMetadata(
            provider="transcript", requested_model="none", latency_ms=0
        )
        return result

    async def _performer_attribution(self, run, request):
        chunks, expected = await self._read_all(run)
        nodes = [self._record(run, chunk.evidence()) for chunk in chunks]
        statements = []
        # Inspect the entire selected caption inventory, not just top-k hits.
        # Only caption passages with possible explicit speaker/performer cues go
        # to the model. Titles/history cannot supply a missing attribution.
        candidates = [node for node in nodes if has_performer_cues(node["text"])]
        for group in self._groups("performer_attribution", request, candidates):
            output = await self._generate(run, payload("performer_attribution", request, group))
            statements.extend(output.statements)
            if len(statements) > 100:
                raise error(
                    "analysis_budget_exceeded", "Attribution output exceeds statement limit"
                )
        run.processed.update(run.records)
        run.notes.append(
            "ตรวจจากบทถอดเสียงและเวลาของทุกส่วนที่นำเข้าได้ "
            "ไม่ได้ระบุตัวบุคคลจากเสียงหรือภาพ และชื่อศิลปินอย่างเดียวไม่ยืนยันว่าใครร้องท่อนไหน"
        )
        output = GeneratedAnswer(
            status="answered" if statements else "insufficient_evidence",
            statements=statements,
            message=""
            if statements
            else (
                "ยังระบุท่อนของผู้ร้องที่ถามไม่ได้จากข้อมูลที่นำเข้า "
                "ระบบตรวจบทถอดเสียงพร้อมเวลาแล้ว แต่ยังไม่มีหลักฐานระบุชื่อผู้ร้องกับช่วงนั้นอย่างชัดเจน "
                "ต้องมีคำบรรยายที่ติดชื่อผู้ร้อง หรือข้อมูลจากเจ้าของคลิปที่ระบุว่าใครร้องช่วงเวลาใด"
            ),
        )
        return await self._finish(
            run,
            output,
            expected,
            full=True,
            checked_ids=list(run.records) if not statements else None,
        )

    async def analyze(self, request, sources, context):
        run = self._run(sources, context, {"analysis", "research"})
        request = self._request(AnalysisRequest, request, run)
        if request["type"] == "compare" and len(run.sources) < 2:
            raise error("invalid_scope", "Comparison needs at least two videos", status=422)
        chunks, expected = await self._read_all(run)
        nodes = [self._record(run, chunk.evidence()) for chunk in chunks]
        if not nodes:
            return await self._finish(
                run,
                GeneratedAnswer(status="insufficient_evidence", message="ไม่มีหลักฐานพร้อมวิเคราะห์"),
                expected,
                full=True,
            )
        # First process bounded batches per video; every original chunk participates.
        summaries = []
        for source in run.sources:
            selected = [n for n in nodes if n["video_id"] == source.video_id]
            for group in self._groups("summarize_batch", request, selected):
                result = await self._generate(run, payload("summarize_batch", request, group))
                run.processed.update(cid for n in group for cid in n["citation_ids"])
                summaries.extend(self._nodes(run, result))
                if result.status == "insufficient_evidence":
                    run.notes.append(
                        f"Evidence batch for {source.video_id} could not be summarized."
                    )
        # Recursively reduce summaries. Fail explicitly if the model does not compress.
        while summaries:
            data = payload(request["type"], request, summaries)
            if input_size(data) <= self.settings.max_context_tokens:
                output = await self._generate(run, data)
                break
            reduced = []
            for group in self._groups("merge_summaries", request, summaries):
                result = await self._generate(run, payload("merge_summaries", request, group))
                reduced.extend(self._nodes(run, result))
                if result.status == "insufficient_evidence":
                    run.notes.append(
                        "An intermediate summary had insufficient supporting evidence."
                    )
            if len(json_text(reduced).encode()) >= len(json_text(summaries).encode()):
                raise error("context_budget_exceeded", "Intermediate summaries did not compress")
            summaries = reduced
        else:
            output = GeneratedAnswer(
                status="insufficient_evidence", message="หลักฐานไม่เพียงพอสำหรับสรุปหรือเปรียบเทียบ"
            )
        if output.status == "answered":
            cited = {run.records[c].video_id for s in output.statements for c in s.citation_ids}
            available = {record.video_id for record in run.records.values()}
            if cited != available:
                raise error("invalid_citation", "Analysis must cite every available selected video")
        return await self._finish(run, output, expected, full=True)

    @staticmethod
    def _nodes(run, result):
        nodes = []
        for statement in result.statements:
            node = statement.model_dump()
            # Opaque chunk IDs alone cannot tell the synthesis model which video a
            # summary describes. Keep provenance through every level of reduction.
            sources = {}
            for cid in statement.citation_ids:
                record = run.records[cid]
                provenance = sources.setdefault(
                    record.video_id,
                    {
                        "video_id": record.video_id,
                        "title": record.title,
                        "citation_ids": [],
                    },
                )
                provenance["citation_ids"].append(cid)
            node["sources"] = list(sources.values())
            nodes.append(node)
        return nodes

    async def _finish(self, run, output, expected, *, full, checked_ids=None):
        # Recheck ALL processed original records, including those not retained as final citations.
        ids = sorted(run.processed)
        for offset in range(0, len(ids), 1000):
            batch = ids[offset : offset + 1000]
            current = await self._bounded(
                run, lambda _, batch=batch: self.knowledge.evidence(run.sources, batch, run.context)
            )
            by_id = {e.chunk_id: e for e in current}
            if any(by_id.get(cid) != run.records[cid] for cid in batch):
                raise error("source_changed", "Evidence changed before answer finalization")
        cited_ids = list(dict.fromkeys(c for s in output.statements for c in s.citation_ids))
        if checked_ids is not None:
            cited_ids = list(dict.fromkeys(checked_ids))
        if len(cited_ids) > 1000:
            raise error("analysis_budget_exceeded", "Final citations exceed backend limit")
        labels = {cid: str(i + 1) for i, cid in enumerate(cited_ids)}
        citations = []
        for cid in cited_ids:
            record = run.records[cid]
            citations.append(
                Citation(
                    citation_id=labels[cid],
                    chunk_id=cid,
                    video_id=record.video_id,
                    title=record.title,
                    start_seconds=record.start_seconds,
                    end_seconds=record.end_seconds,
                    url=f"{canonical_url(record.video_id)}&t={int(record.start_seconds)}s",
                )
            )
        text = (
            "\n\n".join(
                s.text + " " + " ".join(f"[{labels[c]}]" for c in s.citation_ids)
                for s in output.statements
            )
            if output.status == "answered"
            else output.message
        )
        processed_videos = len({run.records[c].video_id for c in run.processed})
        complete = (
            full
            and expected is not None
            and len(run.processed) == expected
            and processed_videos == len(run.sources)
        )
        if full and not complete and not run.notes:
            run.notes.append("Selected evidence could not be processed completely.")
        if run.notes:
            text += "\n\nข้อจำกัด / Limitations: " + " ".join(dict.fromkeys(run.notes))
        usage = {}
        for meta in run.metadata:
            for key, value in meta.usage.items():
                usage[key] = usage.get(key, 0) + value
        versions = list(dict.fromkeys(m.returned_model for m in run.metadata if m.returned_model))
        providers = list(dict.fromkeys(m.provider for m in run.metadata))
        result = AnswerResult(
            status=output.status,
            answer=text,
            citations=citations,
            coverage=Coverage(
                expected_videos=len(run.sources),
                processed_videos=processed_videos,
                expected_chunks=expected,
                processed_chunks=len(run.processed) if expected is not None else None,
                complete=complete,
                notes=list(dict.fromkeys(run.notes)),
            ),
            provider_metadata=ProviderMetadata(
                provider=",".join(providers) or "none",
                requested_model=self.settings.llm_model,
                returned_model=",".join(versions) or None,
                usage=usage,
                latency_ms=sum(m.latency_ms for m in run.metadata),
            ),
        )
        run.context.check()
        return result

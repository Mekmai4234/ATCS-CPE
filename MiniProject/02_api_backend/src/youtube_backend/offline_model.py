"""Explicit demonstration model. It is not Gemini and makes no network calls."""

from .schemas import ProviderMetadata


class OfflineModel:
    def __init__(self, requested_model):
        self.requested_model = requested_model
        self.closed = False

    def metadata(self):
        return ProviderMetadata(
            provider="fixture",
            requested_model=self.requested_model,
            returned_model="offline-integration-model",
            latency_ms=0,
        )

    async def decide(self, history, timeout):
        from youtube_agent.models import ModelReply

        observations = [entry for entry in history if entry["role"] == "tool"]
        if not observations:
            return ModelReply("read_video_chunks", {}, self.metadata())
        last = observations[-1]
        if last["name"] == "read_video_chunks":
            cursor = last["result"].get("next_cursor")
            if cursor:
                return ModelReply("read_video_chunks", {"cursor": cursor}, self.metadata())
            return ModelReply("create_learning_artifact", {"type": "study_plan"}, self.metadata())
        records = {
            entry["chunk_id"]: entry
            for observation in observations
            for entry in observation["result"].get("evidence", [])
        }
        return ModelReply(
            "finish_research",
            {
                "content": "[OFFLINE FIXTURE] Research based on the supplied excerpts.",
                "citation_ids": list(records),
            },
            self.metadata(),
        )

    async def generate(self, request, records, schema, timeout):
        from youtube_agent.models import Generated

        cid = records[0].chunk_id
        content = {
            "study_plan": {
                "days": [
                    {
                        "day": day,
                        "topic": "[OFFLINE FIXTURE] Study the cited evidence",
                        "citations": [cid],
                    }
                    for day in range(1, request["days"] + 1)
                ]
            },
            "quiz": {
                "questions": [
                    {
                        "question": "[OFFLINE FIXTURE] What does the supplied excerpt say?",
                        "answer": records[0].text,
                        "explanation": "The cited transcript is the source.",
                        "citations": [cid],
                    }
                ]
            },
            "flashcards": {
                "cards": [
                    {
                        "front": "[OFFLINE FIXTURE] Source excerpt",
                        "back": records[0].text,
                        "citations": [cid],
                    }
                ]
            },
        }[request["type"]]
        return Generated(schema.model_validate(content), self.metadata())

    async def close(self):
        self.closed = True

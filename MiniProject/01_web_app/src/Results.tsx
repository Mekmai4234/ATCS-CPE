import QuizContent from './Quiz';
import { StoredFeedback } from './feedbackSession';
import { useState } from 'react';
import { citationUrl, timestamp } from './domain';
import type { Artifact, Citation, Coverage, TaskResult, TaskType } from './types';
import { evidenceLabels } from './domain';
import { FrameEvidence, validFrame, VisualCoverageNotice } from './Evidence';
import { BuddyArt } from './BuddyArt';
import './results-v5.css';

export function Citations({
  citations,
  available = true,
}: {
  citations: Citation[];
  available?: boolean;
}) {
  return (
    <div className="citations">
      {citations.map((citation, i) => {
        const visual = citation.presentation && citation.presentation.kind !== 'transcript';
        const frame = citation.presentation?.frame;
        const active =
          (citation.source_available ?? available) &&
          (!visual || (validFrame(frame) && frame.videoId === citation.video_id));
        const url = active
          ? visual && validFrame(frame)
            ? `https://www.youtube.com/watch?v=${frame.videoId}&t=${Math.floor(frame.timeSeconds)}s`
            : visual
              ? null
              : citationUrl(citation)
          : null;
        return (
          <div className="citation" key={`${citation.citation_id}-${i}`}>
            <span className="source-number">{i + 1}</span>
            <div>
              <strong>{citation.title}</strong>
              <small>
                {citation.kind === 'video'
                  ? 'ภาพและเสียง · AI วิเคราะห์'
                  : evidenceLabels[citation.presentation?.kind || 'transcript']}
              </small>
              <span>
                {visual && validFrame(frame)
                  ? timestamp(frame.timeSeconds)
                  : `${timestamp(citation.start_seconds)}–${timestamp(citation.end_seconds)}`}
              </span>
            </div>
            {url ? (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`เปิดหลักฐาน ${citation.title} ที่ ${timestamp(visual && validFrame(frame) ? frame.timeSeconds : citation.start_seconds)}`}
              >
                เปิดคลิป ↗
              </a>
            ) : (
              <small>แหล่งข้อมูลใช้ไม่ได้</small>
            )}
            {visual && citation.presentation && (
              <FrameEvidence
                key={`${frame?.generation}:${frame?.evidenceVersion}:${frame?.frameId}`}
                evidence={citation.presentation}
                available={active}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
export function CoverageNotice({
  coverage,
  insufficient = false,
}: {
  coverage?: Coverage;
  insufficient?: boolean;
}) {
  if (!coverage) return null;
  if (coverage.expected_videos === 0)
    return <p className="notice">คุยทั่วไป · ไม่ได้อ้างอิงเนื้อหาวิดีโอ</p>;
  return (
    <div className={`coverage ${coverage.complete ? '' : 'warning'}`}>
      <strong>
        {coverage.complete
          ? insufficient
            ? 'ตรวจข้อมูลครบแล้ว แต่ยังยืนยันคำตอบไม่ได้'
            : 'ตรวจสอบแหล่งข้อมูลแล้ว'
          : 'ข้อมูลยังไม่ครอบคลุมทั้งหมด'}
      </strong>
      <span>
        คลิป {coverage.processed_videos}/{coverage.expected_videos}
        {coverage.expected_chunks !== null
          ? ` · ข้อความ ${coverage.processed_chunks}/${coverage.expected_chunks}`
          : ''}
      </span>
      {coverage.notes?.map((note, i) => (
        <span key={i}>
          {note.startsWith('Only evidence actually')
            ? 'นับเฉพาะข้อมูลที่ส่งให้ AI สำเร็จแล้ว บางช่วงอาจยังไม่ได้อ่าน'
            : note.startsWith('Stopped: context_budget_exceeded')
              ? 'ข้อมูลเกินงบต่อคำขอ ลองระบุหัวข้อให้แคบลง'
              : note}
        </span>
      ))}
    </div>
  );
}
function ArtifactReferences({ artifact, ids }: { artifact: Artifact; ids: string[] }) {
  return (
    <Citations
      citations={artifact.citations.filter((c) => ids.includes(c.citation_id))}
      available={artifact.sources_available !== false}
    />
  );
}

function ArtifactPager({
  index,
  count,
  change,
  noun,
}: {
  index: number;
  count: number;
  change: (value: number) => void;
  noun: 'ข้อ' | 'การ์ด';
}) {
  return (
    <nav className="v5r-pager" aria-label={`เปลี่ยน${noun}`}>
      <button type="button" disabled={index === 0} onClick={() => change(index - 1)}>
        <span aria-hidden="true">←</span> {noun}ก่อนหน้า
      </button>
      <span aria-live="polite" aria-atomic="true">
        {noun} {index + 1} / {count}
      </span>
      <button type="button" disabled={index >= count - 1} onClick={() => change(index + 1)}>
        {noun}ถัดไป <span aria-hidden="true">→</span>
      </button>
    </nav>
  );
}

function FlashcardContent({ artifact }: { artifact: Artifact }) {
  const [index, setIndex] = useState(0);
  const cards = artifact.content.cards || [];
  const current = Math.min(index, Math.max(0, cards.length - 1));
  const card = cards[current];
  if (!card) return <p className="v5r-empty">ยังไม่มีการ์ดในผลลัพธ์นี้</p>;
  return (
    <div className="v5r-flash-content">
      <div className="v5r-flash-stack">
        <details className="learning-item v5r-flash-card" key={current}>
          <summary>
            <span className="v5r-position">
              {current + 1} / {cards.length}
            </span>
            <strong>{card.front}</strong>
            <span className="v5r-flip-hint">
              พลิกดูคำตอบ <span aria-hidden="true">↔</span>
            </span>
          </summary>
          <div className="v5r-flash-back">
            <p>{card.back}</p>
            <ArtifactReferences artifact={artifact} ids={card.citations} />
          </div>
        </details>
      </div>
      <ArtifactPager index={current} count={cards.length} change={setIndex} noun="การ์ด" />
    </div>
  );
}

export function ArtifactView({ artifact }: { artifact: Artifact }) {
  const isQuiz = artifact.type === 'quiz';
  const isCards = artifact.type === 'flashcards';
  const label = isQuiz ? 'ทดสอบ' : isCards ? 'ทบทวน' : 'วางแผน';
  const fullLabel = isQuiz ? 'แบบทดสอบ' : isCards ? 'แฟลชการ์ด' : 'แผนเรียน';
  return (
    <section className={`artifact v5r-artifact v5r-artifact-${artifact.type}`}>
      <h3 className="v5r-title" aria-label={fullLabel}>
        {label}
        <span aria-hidden="true">.</span>
      </h3>
      {artifact.sources_available === false && (
        <p className="notice warning">แหล่งข้อมูลเดิมถูกลบหรือเปลี่ยนแปลงแล้ว</p>
      )}
      <div className="v5r-artifact-layout">
        <div className="v5r-art-stage" aria-hidden="true">
          <BuddyArt pose={artifact.type} />
        </div>
        {isQuiz && (
          <QuizContent
            artifact={artifact}
            references={(ids) => <ArtifactReferences artifact={artifact} ids={ids} />}
          />
        )}
        {isCards && <FlashcardContent artifact={artifact} />}
        {artifact.type === 'study_plan' && (
          <div className="v5r-plan-list">
            {artifact.content.days?.map((day) => (
              <article className="learning-item v5r-plan-day" key={day.day}>
                <strong>วันที่ {day.day}</strong>
                <p>{day.topic}</p>
                <ArtifactReferences artifact={artifact} ids={day.citations} />
              </article>
            ))}
            {!artifact.content.days?.length && <p className="v5r-empty">ยังไม่มีแผนในผลลัพธ์นี้</p>}
          </div>
        )}
      </div>
      <CoverageNotice coverage={artifact.coverage} />
    </section>
  );
}
export function ResultView({
  result,
  partial = false,
  kind = 'chat',
}: {
  result: TaskResult;
  partial?: boolean;
  kind?: TaskType;
}) {
  if (result.visibility === 'withheld')
    return (
      <p className="notice" role="status">
        ระบบระงับคำตอบนี้ กรุณาปรับคำถามแล้วส่งใหม่
      </p>
    );
  const illustrated =
    ['summary', 'compare', 'research'].includes(kind) && !result.artifacts?.length;
  const answer = result.answer || (typeof result.content === 'string' ? result.content : '');
  const label = kind === 'compare' ? 'เทียบ' : kind === 'research' ? 'ค้นคว้า' : 'สรุป';
  return (
    <div className={`result-content v5r-result v5r-result-${kind}`}>
      {partial && (
        <p className="notice warning" role="status">
          ได้ผลบางส่วน — งานนี้ยังไม่สำเร็จครบถ้วน
        </p>
      )}
      {result.status === 'insufficient_evidence' && (
        <h3 className="insufficient">หลักฐานไม่เพียงพอ</h3>
      )}
      {result.sources_available === false && (
        <p className="notice warning">แหล่งข้อมูลเดิมถูกลบหรือเปลี่ยนแปลงแล้ว</p>
      )}
      {result.provider_metadata?.provider === 'fixture' && (
        <span className="tag">คำตอบสังเคราะห์ · ไม่ใช่ AI จริง</span>
      )}
      <div className={illustrated ? 'v5r-answer-layout' : 'v5r-answer-plain'}>
        <div className="v5r-answer-copy">
          {illustrated && (
            <h3 className="v5r-title">
              {label}
              <span aria-hidden="true">.</span>
            </h3>
          )}
          {answer && <p className="answer-text">{answer}</p>}
          {!!result.citations?.length && (
            <>
              <h4>
                {result.status === 'insufficient_evidence'
                  ? 'แหล่งข้อมูลที่ตรวจสอบ'
                  : 'หลักฐานจากคลิป'}
              </h4>
              <Citations
                citations={result.citations}
                available={result.sources_available !== false}
              />
            </>
          )}
        </div>
        {illustrated && (
          <aside className="v5r-answer-art" aria-hidden="true">
            <BuddyArt pose={kind} />
          </aside>
        )}
      </div>
      {!result.artifacts?.length && (
        <CoverageNotice
          coverage={result.coverage}
          insufficient={result.status === 'insufficient_evidence'}
        />
      )}
      <VisualCoverageNotice value={result.visualCoverage} />
      {kind === 'chat' && result.assistant_message_id && (
        <StoredFeedback key={result.assistant_message_id} id={result.assistant_message_id} />
      )}
      {result.artifacts?.map((artifact, i) => (
        <ArtifactView artifact={artifact} key={artifact.artifact_id || i} />
      ))}
    </div>
  );
}

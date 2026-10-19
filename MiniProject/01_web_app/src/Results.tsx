import { citationUrl, timestamp } from './domain';
import type { Artifact, Citation, Coverage, TaskResult } from './types';

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
        const url = available ? citationUrl(citation) : null;
        return (
          <div className="citation" key={`${citation.citation_id}-${i}`}>
            <span className="source-number">{i + 1}</span>
            <div>
              <strong>{citation.title}</strong>
              <span>
                {timestamp(citation.start_seconds)}–{timestamp(citation.end_seconds)}
              </span>
            </div>
            {url ? (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`เปิดหลักฐาน ${citation.title} ที่ ${timestamp(citation.start_seconds)}`}
              >
                เปิดคลิป ↗
              </a>
            ) : (
              <small>แหล่งข้อมูลใช้ไม่ได้</small>
            )}
          </div>
        );
      })}
    </div>
  );
}
export function CoverageNotice({ coverage }: { coverage?: Coverage }) {
  if (!coverage) return null;
  return (
    <div className={`coverage ${coverage.complete ? '' : 'warning'}`}>
      <strong>
        {coverage.complete ? 'ตรวจสอบแหล่งข้อมูลแล้ว' : 'ข้อมูลยังไม่ครอบคลุมทั้งหมด'}
      </strong>
      <span>
        คลิป {coverage.processed_videos}/{coverage.expected_videos}
        {coverage.expected_chunks !== null
          ? ` · ข้อความ ${coverage.processed_chunks}/${coverage.expected_chunks}`
          : ''}
      </span>
      {coverage.notes?.map((note, i) => (
        <span key={i}>{note}</span>
      ))}
    </div>
  );
}
export function ArtifactView({ artifact }: { artifact: Artifact }) {
  const refs = (ids: string[]) => (
    <Citations
      citations={artifact.citations.filter((c) => ids.includes(c.citation_id))}
      available={artifact.sources_available !== false}
    />
  );
  return (
    <section className="artifact">
      <h3>
        {artifact.type === 'quiz'
          ? 'แบบทดสอบ'
          : artifact.type === 'flashcards'
            ? 'แฟลชการ์ด'
            : 'แผนเรียน'}
      </h3>
      {artifact.type === 'quiz' &&
        artifact.content.questions?.map((q, i) => (
          <article className="learning-item" key={i}>
            <strong>
              {i + 1}. {q.question}
            </strong>
            <details>
              <summary>ดูเฉลยและคำอธิบาย</summary>
              <p>{q.answer}</p>
              <p>{q.explanation}</p>
              {refs(q.citations)}
            </details>
          </article>
        ))}
      {artifact.type === 'flashcards' &&
        artifact.content.cards?.map((c, i) => (
          <details className="learning-item" key={i}>
            <summary>{c.front}</summary>
            <p>{c.back}</p>
            {refs(c.citations)}
          </details>
        ))}
      {artifact.type === 'study_plan' &&
        artifact.content.days?.map((day) => (
          <article className="learning-item" key={day.day}>
            <strong>วันที่ {day.day}</strong>
            <p>{day.topic}</p>
            {refs(day.citations)}
          </article>
        ))}
      <CoverageNotice coverage={artifact.coverage} />
    </section>
  );
}
export function ResultView({ result, partial = false }: { result: TaskResult; partial?: boolean }) {
  return (
    <div className="result-content">
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
      <p className="answer-text">
        {result.answer || (typeof result.content === 'string' ? result.content : '')}
      </p>
      {!!result.citations?.length && (
        <>
          <h4>หลักฐานจากคลิป</h4>
          <Citations citations={result.citations} available={result.sources_available !== false} />
        </>
      )}
      <CoverageNotice coverage={result.coverage} />
      {result.artifacts?.map((artifact, i) => (
        <ArtifactView artifact={artifact} key={artifact.artifact_id || i} />
      ))}
    </div>
  );
}

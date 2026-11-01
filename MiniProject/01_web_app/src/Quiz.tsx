import { useContext, useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ApiError, pollJob } from './api';
import { TaskApiContext } from './TaskApi';
import { jobStatus } from './domain';
import type { Artifact, Job, QuizGrade } from './types';

export default function QuizContent({
  artifact,
  references,
}: {
  artifact: Artifact;
  references: (ids: string[]) => ReactNode;
}) {
  const api = useContext(TaskApiContext);
  const [index, setIndex] = useState(0);
  const [drafts, setDrafts] = useState<Record<number, string>>(() =>
    Object.fromEntries((artifact.submitted_answers || []).map((answer, i) => [i, answer])),
  );
  const [grade, setGrade] = useState<QuizGrade | undefined>(artifact.grading);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const savedJob = useRef<string | null>(artifact.grading_job_id || null);
  const latest = useRef<Job | null>(null);
  const key = useRef(crypto.randomUUID());
  const frozenAnswers = useRef<string[] | null>(artifact.submitted_answers || null);
  const controller = useRef<AbortController | null>(null);
  const answerId = useId();
  const questions = artifact.content.questions || [];
  const current = Math.min(index, Math.max(0, questions.length - 1));
  const question = questions[current];
  useEffect(() => () => controller.current?.abort(), []);
  async function follow(id: string, signal: AbortSignal) {
    if (!api) return;
    const job = await pollJob(
      api,
      id,
      (update) => {
        latest.current = update;
        setStatus(jobStatus(update));
        if (update.state === 'paused') throw new Error(jobStatus(update));
      },
      signal,
    );
    if (job.state !== 'completed' || !job.result) throw new Error(jobStatus(job));
    const result = job.result as unknown as QuizGrade;
    if (
      !Array.isArray(result.marks) ||
      result.marks.length !== questions.length ||
      result.marks.some(
        (mark) => typeof mark.correct !== 'boolean' || typeof mark.feedback !== 'string',
      ) ||
      result.total !== questions.length ||
      result.correct !== result.marks.filter((mark) => mark.correct).length
    )
      throw new Error('ผลตรวจคำตอบไม่สมบูรณ์ กรุณาติดตามงานเดิมอีกครั้ง');
    setGrade(result);
    setStatus('ตรวจคำตอบแล้ว');
  }
  async function submit() {
    if (!api || !artifact.artifact_id || busy) return;
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    setBusy(true);
    setError('');
    try {
      if (savedJob.current && ['paused', 'failed'].includes(latest.current?.state || '')) {
        const { data } = await api.request<{ job_id: string }>(
          `/api/jobs/${encodeURIComponent(savedJob.current)}/resume`,
          { method: 'POST', body: '{}', signal: c.signal },
        );
        savedJob.current = data.job_id;
      }
      if (!savedJob.current) {
        frozenAnswers.current ||= questions.map((_, i) => drafts[i] || '');
        const { data } = await api.request<{ job_id: string }>(
          `/api/learning-artifacts/${encodeURIComponent(artifact.artifact_id)}/submit`,
          {
            method: 'POST',
            headers: { 'Idempotency-Key': key.current },
            signal: c.signal,
            body: JSON.stringify({ answers: frozenAnswers.current }),
          },
        );
        savedJob.current = data.job_id;
      }
      await follow(savedJob.current, c.signal);
    } catch (reason) {
      if (!savedJob.current && reason instanceof ApiError && !reason.retryable && !reason.jobId) {
        frozenAnswers.current = null;
        key.current = crypto.randomUUID();
      }
      if (!c.signal.aborted)
        setError(
          reason instanceof ApiError && reason.code === 'quota_unavailable'
            ? 'กำลังรอโควตา คำตอบของคุณถูกเก็บไว้แล้ว ลองติดตามอีกครั้งเมื่อพร้อม'
            : reason instanceof Error
              ? reason.message
              : 'ตรวจคำตอบไม่สำเร็จ',
        );
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  useEffect(() => {
    if (artifact.grading_job_id && !grade) void submit();
  }, [artifact.grading_job_id]);
  if (!question) return <p className="v5r-empty">ยังไม่มีคำถามในผลลัพธ์นี้</p>;
  if (grade)
    return (
      <div className="v5r-quiz-content" aria-label="ผลแบบทดสอบ">
        <section className="quiz-score" role="status">
          <strong>
            {grade.correct} / {grade.total}
          </strong>
          <p>
            ถูก {grade.correct} ข้อ · ผิด {grade.total - grade.correct} ข้อ
          </p>
          <small>ประเมินคำตอบอัตนัยโดย AI เทียบกับเฉลยของแบบทดสอบ</small>
        </section>
        {questions.map((item, i) => (
          <article className="learning-item" key={i}>
            <h4>
              {i + 1}. {item.question}
            </h4>
            <strong>{grade.marks[i].correct ? 'ถูกต้อง' : 'ยังไม่ถูกต้อง'}</strong>
            <p>คำตอบของคุณ: {grade.answers?.[i] || drafts[i] || 'ไม่ได้ตอบ'}</p>
            <p>{grade.marks[i].feedback}</p>
            <details className="v5r-explanation">
              <summary>เฉลยข้อ {i + 1}</summary>
              <p>{item.answer}</p>
              <p>{item.explanation}</p>
              {references(item.citations)}
            </details>
          </article>
        ))}
        <button
          className="secondary"
          onClick={() => {
            setGrade(undefined);
            setDrafts({});
            setIndex(0);
            savedJob.current = null;
            latest.current = null;
            key.current = crypto.randomUUID();
            frozenAnswers.current = null;
            setError('');
            setStatus('');
          }}
        >
          ทำแบบทดสอบอีกครั้ง
        </button>
      </div>
    );
  return (
    <div className="v5r-quiz-content">
      <article className="learning-item v5r-question-card" key={current}>
        <span className="v5r-position">
          ข้อ {current + 1} / {questions.length}
        </span>
        <strong className="v5r-question-title">
          {current + 1}. {question.question}
        </strong>
        <label htmlFor={answerId}>คำตอบของคุณ</label>
        <textarea
          id={answerId}
          rows={3}
          maxLength={2000}
          value={drafts[current] || ''}
          disabled={busy || !!savedJob.current || !!frozenAnswers.current}
          placeholder="ลองตอบด้วยคำของคุณ"
          onChange={(event) =>
            setDrafts((previous) => ({ ...previous, [current]: event.target.value }))
          }
        />
        <small>ส่งคำตอบทั้งหมดเพื่อดูคะแนนและเฉลย</small>
      </article>
      <nav className="v5r-pager" aria-label="เปลี่ยนข้อ">
        <button type="button" disabled={current === 0} onClick={() => setIndex(current - 1)}>
          ← ข้อก่อนหน้า
        </button>
        <span>
          ตอบแล้ว {questions.filter((_, i) => drafts[i]?.trim()).length}/{questions.length}
        </span>
        {current < questions.length - 1 ? (
          <button type="button" onClick={() => setIndex(current + 1)}>
            ข้อถัดไป →
          </button>
        ) : (
          <button
            type="button"
            className="primary"
            disabled={busy || !api || !artifact.artifact_id || artifact.sources_available === false}
            onClick={() => void submit()}
          >
            {busy ? 'กำลังตรวจคำตอบ…' : savedJob.current ? 'ติดตามการตรวจคำตอบ' : 'ส่งคำตอบ'}
          </button>
        )}
      </nav>
      {status && <p role="status">{status}</p>}
      {error && (
        <p className="notice warning" role="alert">
          {error}
        </p>
      )}
      {!artifact.artifact_id && <p>เปิดแบบทดสอบที่บันทึกไว้เพื่อตรวจคำตอบ</p>}
    </div>
  );
}

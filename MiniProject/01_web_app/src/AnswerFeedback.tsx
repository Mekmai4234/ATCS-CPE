import { useEffect, useRef, useId, useState } from 'react';
import './feedback.css';

export type Feedback = { rating: 'like' | 'dislike'; reason: string; comment: string };
export interface FeedbackPort {
  save: (messageId: string, feedback: Feedback | null) => Promise<Feedback | null>;
}
const reasons = [
  'ตอบไม่ตรงคำถาม',
  'ข้อมูลผิด',
  'อ้างอิงไม่ตรง',
  'ข้อมูลไม่พอ',
  'ภาษาหรือเนื้อหาไม่เหมาะสม',
  'อื่น ๆ',
];

// Mount keyed by member ID + stable assistant message ID, only for persisted chat answers.
// The parent owns server-loaded state and shares updates across full/floating/history views.
export default function AnswerFeedback({
  messageId,
  value,
  port,
  onSaved,
}: {
  messageId: string;
  value: Feedback | null;
  port: FeedbackPort;
  onSaved: (value: Feedback | null) => void;
}) {
  const id = useId();
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  const [saved, setSaved] = useState(false);
  const [details, setDetails] = useState(false);
  const [reason, setReason] = useState(value?.reason || '');
  const [comment, setComment] = useState(value?.comment || '');
  const [retry, setRetry] = useState<{ value: Feedback | null }>();
  async function submit(next: Feedback | null) {
    if (pending || !messageId) return;
    setPending(true);
    setError(false);
    setSaved(false);
    try {
      const confirmed = await port.save(messageId, next);
      if (!active.current) return;
      onSaved(confirmed);
      setSaved(true);
      setRetry(undefined);
      if (confirmed?.rating !== 'dislike') setDetails(false);
    } catch {
      if (!active.current) return;
      setError(true);
      setRetry({ value: next });
    } finally {
      if (active.current) setPending(false);
    }
  }
  return (
    <section className="answer-feedback" aria-label="ความคิดเห็นต่อคำตอบ" aria-busy={pending}>
      <div className="feedback-actions">
        {(['like', 'dislike'] as const).map((rating) => (
          <button
            type="button"
            key={rating}
            aria-label={rating === 'like' ? 'ถูกใจ' : 'ไม่ถูกใจ'}
            aria-pressed={value?.rating === rating}
            disabled={pending}
            onClick={() => {
              if (rating === 'dislike') {
                setReason(value?.reason || '');
                setComment(value?.comment || '');
                setDetails(true);
              }
              void submit(value?.rating === rating ? null : { rating, reason: '', comment: '' });
            }}
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              width="20"
              height="20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              style={{ transform: rating === 'dislike' ? 'rotate(180deg)' : undefined }}
            >
              <path d="M7 10v11H3V10h4Zm0 0 5-7c2 0 2 2 1 6h6c2 0 2 2 1 4l-2 8H7" />
            </svg>
            {value?.rating === rating && <span aria-hidden="true">✓</span>}
          </button>
        ))}
        {value?.rating === 'dislike' && (
          <button
            type="button"
            onClick={() => {
              setReason(value.reason);
              setComment(value.comment);
              setDetails(!details);
            }}
          >
            รายละเอียด
          </button>
        )}
      </div>
      {details && (
        <div className="feedback-details">
          <label htmlFor={`${id}-reason`}>เหตุผล (ไม่บังคับ)</label>
          <select
            id={`${id}-reason`}
            value={reason}
            disabled={pending}
            onChange={(e) => setReason(e.target.value)}
          >
            <option value="">ไม่ระบุ</option>
            {reasons.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
          <label htmlFor={`${id}-comment`}>รายละเอียดเพิ่มเติม (ไม่บังคับ)</label>
          <textarea
            id={`${id}-comment`}
            maxLength={500}
            value={comment}
            disabled={pending}
            onChange={(e) => setComment(e.target.value)}
          />
          <small>{comment.length}/500</small>
          <button
            type="button"
            disabled={pending}
            onClick={() => void submit({ rating: 'dislike', reason, comment })}
          >
            บันทึก
          </button>
        </div>
      )}
      <span role="status">{pending ? 'กำลังบันทึก…' : saved ? 'รับความคิดเห็นแล้ว' : ''}</span>
      {error && (
        <p role="alert">
          บันทึกไม่สำเร็จ คะแนนเดิมยังอยู่{' '}
          <button
            type="button"
            disabled={pending}
            onClick={() => retry && void submit(retry.value)}
          >
            ลองใหม่
          </button>
        </p>
      )}
    </section>
  );
}

import { createContext, useContext, useEffect, useRef, useState } from 'react';
import type { Api } from './api';
import AnswerFeedback, { type Feedback } from './AnswerFeedback';
export type WireFeedback = { rating: 'like' | 'dislike'; reason?: string | null; comment?: string };
export const feedbackReasons: Record<string, string> = {
  ตอบไม่ตรงคำถาม: 'off_topic',
  ข้อมูลผิด: 'incorrect',
  อ้างอิงไม่ตรง: 'citation_mismatch',
  ข้อมูลไม่พอ: 'insufficient_evidence',
  ภาษาหรือเนื้อหาไม่เหมาะสม: 'inappropriate',
  'อื่น ๆ': 'other',
};
export const fromWire = (value: WireFeedback | null): Feedback | null =>
  value
    ? {
        rating: value.rating,
        reason:
          Object.keys(feedbackReasons).find((key) => feedbackReasons[key] === value.reason) || '',
        comment: value.comment || '',
      }
    : null;
export const toWire = (value: Feedback | null): WireFeedback | null =>
  value
    ? value.rating === 'like'
      ? { rating: 'like' }
      : { rating: 'dislike', reason: feedbackReasons[value.reason] || null, comment: value.comment }
    : null;
export const FeedbackApi = createContext<Api | null>(null);
const updates = new WeakMap<Api, EventTarget>();
function bus(api: Api) {
  let value = updates.get(api);
  if (!value) {
    value = new EventTarget();
    updates.set(api, value);
  }
  return value;
}
export function StoredFeedback({ id }: { id: string }) {
  const api = useContext(FeedbackApi);
  const [value, setValue] = useState<Feedback | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);
  const sequence = useRef(0);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!api) return;
    const controller = new AbortController();
    setReady(false);
    setError(false);
    setValue(null);
    const load = () => {
      const version = ++sequence.current;
      void api
        .feedback(id, controller.signal)
        .then((data) => {
          if (
            !controller.signal.aborted &&
            version === sequence.current &&
            data.message_id === id
          ) {
            setValue(fromWire(data.feedback));
            setReady(true);
          }
        })
        .catch(() => {
          if (!controller.signal.aborted && version === sequence.current) setError(true);
        });
    };
    load();
    bus(api).addEventListener(id, load);
    return () => {
      controller.abort();
      bus(api).removeEventListener(id, load);
    };
  }, [api, id, attempt]);
  if (!api) return null;
  if (error)
    return (
      <p role="alert">
        โหลดความคิดเห็นไม่ได้{' '}
        <button onClick={() => setAttempt((n) => n + 1)}>ลองโหลดความคิดเห็นใหม่</button>
      </p>
    );
  if (!ready) return <p role="status">กำลังโหลดความคิดเห็น…</p>;
  return (
    <AnswerFeedback
      key={id}
      messageId={id}
      value={value}
      onSaved={(next) => {
        setValue(next);
        bus(api).dispatchEvent(new Event(id));
      }}
      port={{
        save: async (mid, next) => {
          const result = await api.saveFeedback(mid, toWire(next));
          if (result.message_id !== mid) throw new Error('message mismatch');
          return fromWire(result.feedback);
        },
      }}
    />
  );
}

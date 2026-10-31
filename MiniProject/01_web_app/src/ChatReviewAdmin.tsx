import { useEffect, useRef, useState } from 'react';
import { Api, ApiError } from './api';
const labelNames: Record<string, string> = {
  user_dissatisfied: 'ผู้ใช้ไม่พอใจ',
  answer_risk_suspected: 'ระบบสงสัยคำตอบเสี่ยง',
  direct_abuse: 'คำพูดคุกคาม',
  rule_bypass_suspected: 'สงสัยสั่งข้ามกติกา',
};
const statusNames: Record<string, string> = {
  new: 'ใหม่',
  in_review: 'กำลังตรวจ',
  reviewed: 'ตรวจแล้ว',
};
type Case = {
  case_id: string;
  message_id?: string;
  notes?: string;
  question_excerpt: string;
  member_ref: string;
  source: string;
  label: string;
  status: string;
  feedback?: { rating: string };
};
type Detail = {
  case: Case | null;
  question?: { content: string };
  answer?: { content: string };
  visibility?: string;
  provider_metadata?: { requested_model?: string; returned_model?: string };
  review_signal?: unknown;
  moderation?: {
    direction?: 'input' | 'output';
    draft: string | null;
    action: string;
    reason: string;
    policy_version: string;
    visible_to_user: boolean;
  };
  feedback?: { rating: string; reason: string; comment: string };
  citations?: { title: string; start_seconds: number }[];
  scope?: { video_id: string; transcript_version: string }[];
};
export default function ChatReviewAdmin({ api }: { api: Api }) {
  const [mode, setMode] = useState<'cases' | 'messages'>('cases');
  const [items, setItems] = useState<Case[]>([]),
    [detail, setDetail] = useState<Detail | null>(null);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [offset, setOffset] = useState(0),
    [total, setTotal] = useState(0),
    [query, setQuery] = useState('');
  const [status, setStatus] = useState(''),
    [rating, setRating] = useState(''),
    [label, setLabel] = useState('');
  const [after, setAfter] = useState(''),
    [before, setBefore] = useState('');
  const [error, setError] = useState(''),
    [loading, setLoading] = useState(false),
    [revision, setRevision] = useState(0);
  const [notes, setNotes] = useState('');
  const failure = (e: unknown) => {
    if (e instanceof ApiError && [401, 403, 404].includes(e.status || 0)) {
      setItems([]);
      setDetail(null);
      setStats({});
    }
    setError(
      e instanceof ApiError && e.status === 403
        ? 'ไม่มีสิทธิ์ตรวจเนื้อหาแชท หรือยังไม่เปิดใช้งาน'
        : e instanceof ApiError && e.status === 404
          ? 'เคสนี้หมดอายุหรือใช้ไม่ได้แล้ว'
          : 'โหลดหรือบันทึกไม่สำเร็จ กรุณาลองใหม่',
    );
  };
  useEffect(() => {
    const c = new AbortController();
    request.current?.abort();
    setLoading(true);
    setError('');
    setDetail(null);
    setItems([]);
    const p = new URLSearchParams({ limit: '20', offset: String(offset) });
    for (const [k, v] of Object.entries({
      q: query,
      status,
      rating,
      label,
      after: after ? String(new Date(`${after}T00:00:00`).getTime() / 1000) : '',
      before: before ? String(new Date(`${before}T23:59:59`).getTime() / 1000) : '',
    }))
      if (v) p.set(k, v);
    void api
      .request<{ items: Case[]; total: number; stats: Record<string, number> }>(
        mode === 'cases'
          ? `/api/admin/chat-reviews?${p}`
          : `/api/admin/chat-messages?limit=20&offset=${offset}${rating ? `&rating=${rating}` : ''}`,
        { signal: c.signal, cache: 'no-store' },
      )
      .then(({ data }) => {
        if (!c.signal.aborted) {
          setItems(data.items);
          setTotal(data.total);
          if (data.stats) setStats(data.stats);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) failure(e);
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [api, offset, query, status, rating, label, after, before, revision, mode]);
  useEffect(
    () => () => {
      request.current?.abort();
    },
    [],
  );
  const request = useRef<AbortController | null>(null);
  async function open(id: string) {
    request.current?.abort();
    const c = new AbortController();
    request.current = c;
    setDetail(null);
    setLoading(true);
    setError('');
    setNotes('');
    try {
      const { data } = await api.request<Detail>(
        `/api/admin/${mode === 'cases' ? 'chat-reviews' : 'chat-messages'}/${encodeURIComponent(id)}`,
        { signal: c.signal, cache: 'no-store' },
      );
      if (!c.signal.aborted) {
        setDetail(data);
        setNotes(data.case?.notes || '');
      }
    } catch (e) {
      if (!c.signal.aborted) failure(e);
    } finally {
      if (!c.signal.aborted) setLoading(false);
    }
  }
  async function save(outcome?: string) {
    if (!detail?.case || loading) return;
    setLoading(true);
    setError('');
    request.current?.abort();
    const c = new AbortController();
    request.current = c;
    try {
      const { data: updated } = await api.request<Case>(
        `/api/admin/chat-reviews/${encodeURIComponent(detail.case.case_id)}`,
        {
          signal: c.signal,
          method: 'PATCH',
          body: JSON.stringify({
            status: outcome ? 'reviewed' : 'in_review',
            outcome: outcome || null,
            notes,
          }),
        },
      );
      if (!c.signal.aborted) {
        setDetail((previous) =>
          previous && previous.case && previous.case.case_id === detail.case?.case_id
            ? { ...previous, case: { ...previous.case, ...updated } }
            : previous,
        );
        setItems((previous) =>
          outcome && (!status || status === 'new' || status === 'in_review')
            ? previous.filter((item) => item.case_id !== detail.case?.case_id)
            : previous.map((item) =>
                item.case_id === detail.case?.case_id ? { ...item, ...updated } : item,
              ),
        );
        if (outcome && (!status || status === 'new' || status === 'in_review'))
          setTotal((n) => Math.max(0, n - 1));
        if (outcome)
          setStats((previous) => ({
            ...previous,
            pending: Math.max(0, (previous.pending || 0) - 1),
          }));
      }
    } catch (e) {
      if (!c.signal.aborted) failure(e);
    } finally {
      if (!c.signal.aborted) setLoading(false);
    }
  }
  return (
    <section className="admin-card" aria-label="ตรวจสอบแชท">
      <h1>ตรวจสอบแชท</h1>
      <button
        aria-pressed={mode === 'cases'}
        onClick={() => {
          if (mode === 'cases') return;
          setRating('');
          setItems([]);
          setDetail(null);
          setMode('cases');
          setOffset(0);
        }}
      >
        คิวตรวจ
      </button>
      <button
        aria-pressed={mode === 'messages'}
        onClick={() => {
          if (mode === 'messages' && !rating) return;
          setRating('');
          setItems([]);
          setDetail(null);
          setMode('messages');
          setOffset(0);
        }}
      >
        แชทที่บันทึกทั้งหมด
      </button>
      <button
        aria-pressed={mode === 'messages' && rating === 'like'}
        onClick={() => {
          if (mode === 'messages' && rating === 'like') return;
          setItems([]);
          setDetail(null);
          setMode('messages');
          setRating('like');
          setOffset(0);
        }}
      >
        คำตอบที่ถูกใจ
      </button>
      <div className="admin-stats">
        {Object.entries({
          like: 'ถูกใจ',
          dislike: 'ไม่ถูกใจ',
          pending: 'รอตรวจ',
          withheld: 'ระบบระงับ',
        }).map(([k, v]) => (
          <article key={k}>
            {v}: {stats[k] ?? '—'}
          </article>
        ))}
      </div>
      <fieldset disabled={mode === 'messages'} style={{ border: 0, padding: 0, margin: 0 }}>
        <legend>ตัวกรองคิวตรวจ</legend>
        <label>
          ค้นคำถาม
          <input
            value={query}
            onChange={(e) => {
              setOffset(0);
              setQuery(e.target.value);
            }}
          />
        </label>
        <label>
          สถานะ
          <select
            aria-label="สถานะ"
            value={status}
            onChange={(e) => {
              setOffset(0);
              setStatus(e.target.value);
            }}
          >
            <option value="">รอตรวจ</option>
            <option value="new">ใหม่</option>
            <option value="in_review">กำลังตรวจ</option>
            <option value="reviewed">ตรวจแล้ว</option>
          </select>
        </label>
        <label>
          คะแนน
          <select
            aria-label="คะแนน"
            value={rating}
            onChange={(e) => {
              setOffset(0);
              setRating(e.target.value);
              if (e.target.value === 'like') {
                setItems([]);
                setDetail(null);
                setMode('messages');
              }
            }}
          >
            <option value="">ทุกคะแนน</option>
            <option value="like">ถูกใจ</option>
            <option value="dislike">ไม่ถูกใจ</option>
          </select>
        </label>
        <label>
          ประเภทเหตุการณ์
          <input
            value={label}
            onChange={(e) => {
              setOffset(0);
              setLabel(e.target.value);
            }}
          />
        </label>
        <label>
          ตั้งแต่
          <input
            type="date"
            value={after}
            onChange={(e) => {
              setOffset(0);
              setAfter(e.target.value);
            }}
          />
        </label>
        <label>
          ถึง
          <input
            type="date"
            value={before}
            onChange={(e) => {
              setOffset(0);
              setBefore(e.target.value);
            }}
          />
        </label>
      </fieldset>
      {loading && <p role="status">กำลังโหลด…</p>}
      {error && (
        <p role="alert">
          {error}
          <button onClick={() => setRevision((n) => n + 1)}>ลองใหม่</button>
        </p>
      )}
      {!loading && !error && !items.length && <p>ไม่มีรายการที่ตรงกับตัวกรอง</p>}
      {items.map((item) => (
        <article key={mode === 'cases' ? item.case_id : item.message_id}>
          <p>{item.question_excerpt || `คำตอบที่บันทึก ${item.message_id?.slice(0, 8) || ''}`}</p>
          {mode === 'cases' ? (
            <small>
              สมาชิก {item.member_ref} ·{' '}
              {['user', 'user_report'].includes(item.source) ? 'ผู้ใช้รายงาน' : 'ระบบสงสัย'} ·{' '}
              {labelNames[item.label] || item.label} · {statusNames[item.status] || item.status}
            </small>
          ) : (
            <small>
              {item.feedback
                ? item.feedback.rating === 'like'
                  ? 'ผู้ใช้กดถูกใจ'
                  : 'ผู้ใช้กดไม่ถูกใจ'
                : 'คำตอบที่บันทึกไว้ — ไม่ได้ระบุว่าเป็นปัญหา'}
            </small>
          )}
          <button
            disabled={loading}
            onClick={() =>
              void open(item.message_id && mode === 'messages' ? item.message_id : item.case_id)
            }
          >
            เปิดดู
          </button>
        </article>
      ))}
      <nav>
        <button
          disabled={loading || offset === 0}
          onClick={() => setOffset((n) => Math.max(0, n - 20))}
        >
          หน้าก่อนหน้า
        </button>
        <button
          disabled={loading || offset + items.length >= total}
          onClick={() => setOffset((n) => n + 20)}
        >
          หน้าถัดไป
        </button>
      </nav>
      {detail && (
        <article>
          <h2>คำถามและคำตอบคู่เดียวกัน</h2>
          <p>{detail.question?.content || 'ข้อความถูกบล็อกก่อนสร้างงาน'}</p>
          <h3>
            {detail.visibility === 'withheld' ? 'ข้อความระบบที่ผู้ใช้เห็น' : 'คำตอบที่ผู้ใช้เห็น'}
          </h3>
          <p>{detail.answer?.content || 'ไม่มีคำตอบ'}</p>
          {detail.moderation?.direction === 'input' &&
            detail.moderation.action === 'block' &&
            !detail.moderation.visible_to_user && (
              <section aria-label="ต้นฉบับข้อความที่ถูกบล็อก">
                <h3>ข้อความผู้ใช้ที่ถูกบล็อกก่อนส่งให้ AI</h3>
                <p>{detail.moderation.draft ?? 'เนื้อหาถูกลบตามอายุการเก็บ'}</p>
              </section>
            )}
          {detail.moderation?.action === 'withhold' && !detail.moderation.visible_to_user && (
            <details>
              <summary>ร่างที่ถูกระงับ — ผู้ใช้ไม่เห็น</summary>
              <p>{detail.moderation.draft || 'เนื้อหาถูกลบตามอายุการเก็บ'}</p>
            </details>
          )}
          {detail.provider_metadata && (
            <p>
              โมเดล:{' '}
              {detail.provider_metadata.returned_model || detail.provider_metadata.requested_model}
            </p>
          )}
          {detail.moderation?.action === 'signal' && (
            <p>สัญญาณระบบเพื่อรอตรวจ — ไม่ใช่ร่างที่ถูกระงับหรือคำตัดสินยืนยัน</p>
          )}
          {detail.moderation && (
            <p>
              นโยบายตรวจ: {detail.moderation.policy_version} · เหตุผล: {detail.moderation.reason}
            </p>
          )}
          {detail.feedback && (
            <p>
              ผู้ใช้รายงาน: {detail.feedback.rating === 'dislike' ? 'ไม่ถูกใจ' : 'ถูกใจ'} ·{' '}
              {detail.feedback.reason} · {detail.feedback.comment}
            </p>
          )}
          <ul>
            {detail.scope?.map((s) => (
              <li key={s.video_id}>
                {s.video_id} · เวอร์ชัน {s.transcript_version}
              </li>
            ))}
          </ul>
          <ul>
            {detail.citations?.map((c, i) => (
              <li key={i}>
                {c.title} · {c.start_seconds} วินาที
              </li>
            ))}
          </ul>
          <label>
            หมายเหตุ
            <textarea
              aria-label="หมายเหตุ"
              maxLength={1000}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>
          {detail.case?.status === 'new' ? (
            <button disabled={loading} onClick={() => void save()}>
              เริ่มตรวจ
            </button>
          ) : detail.case?.status === 'in_review' ? (
            ['confirmed', 'false_positive', 'inconclusive'].map((v, i) => (
              <button key={v} disabled={loading} onClick={() => void save(v)}>
                {['ยืนยันปัญหา', 'แจ้งเตือนผิด', 'ยังสรุปไม่ได้'][i]}
              </button>
            ))
          ) : (
            <p>{detail.case ? 'ตรวจแล้ว' : 'คำตอบปกติ — ยังไม่มีเคสตรวจ'}</p>
          )}
        </article>
      )}
    </section>
  );
}

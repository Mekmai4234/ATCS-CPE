import { useEffect, useState } from 'react';
import { Api } from './api';
import type { ConversationSummary, Video } from './types';
import { serviceMessage, userMessages } from './userMessages';
import { ApiError } from './api';

export default function ChatHistory({
  api,
  videos,
  locked,
  open,
  start,
}: {
  api: Api;
  videos: Video[];
  locked: boolean;
  open: (id: string) => void;
  start: () => void;
}) {
  const [draft, setDraft] = useState('');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setItems([]);
    void api
      .conversations(query, offset, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setItems(data.items);
        setTotal(data.total);
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setError(
            error instanceof ApiError
              ? serviceMessage(error.code, error.status) || 'โหลดประวัติแชตไม่ได้ กรุณาลองใหม่'
              : userMessages.connection,
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [api, query, offset, attempt]);
  return (
    <section className="history-panel" aria-labelledby="history-title">
      <div className="section-heading">
        <div>
          <h2 id="history-title">บทสนทนาที่ผ่านมา</h2>
          <p>กลับมาอ่านคำตอบ หรือเรียนรู้ต่อจากคำถามเดิม</p>
        </div>
        <button className="primary" disabled={locked} onClick={start}>
          เริ่มแชตใหม่
        </button>
      </div>
      <form
        className="history-search"
        onSubmit={(event) => {
          event.preventDefault();
          setOffset(0);
          setQuery(draft.trim());
        }}
      >
        <label htmlFor="history-search">ค้นหาจากชื่อบทสนทนา</label>
        <div>
          <input
            id="history-search"
            value={draft}
            maxLength={160}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="พิมพ์คำถามที่เคยถาม…"
          />
          <button className="secondary" disabled={loading}>
            ค้นหาประวัติ
          </button>
        </div>
      </form>
      {loading && <p role="status">กำลังโหลดประวัติแชต…</p>}
      {error && (
        <div className="notice error" role="alert">
          {error}
          <button onClick={() => setAttempt((n) => n + 1)}>ลองโหลดประวัติอีกครั้ง</button>
        </div>
      )}
      {!loading && !error && !items.length && (
        <div className="empty-state">
          <h3>{query ? 'ไม่พบบทสนทนาที่ตรงคำค้น' : 'เริ่มบทสนทนาแรกกับ Video Buddy'}</h3>
          <p>
            {query
              ? 'ลองใช้คำอื่นจากคำถามแรกของบทสนทนา'
              : 'เมื่อคุณส่งคำถาม ประวัติจะบันทึกไว้ที่นี่'}
          </p>
        </div>
      )}
      {!loading && !error && (
        <>
          <p className="history-total" role="status">
            {total} บทสนทนา{items.length ? ` · แสดง ${offset + 1}–${offset + items.length}` : ''}
          </p>
          <div className="history-list">
            {items.map((item) => (
              <article key={item.conversation_id}>
                <div>
                  <time dateTime={item.updated_at}>
                    {new Date(item.updated_at).toLocaleString('th-TH', {
                      dateStyle: 'medium',
                      timeStyle: 'short',
                    })}
                  </time>
                  <h3>
                    <button disabled={locked} onClick={() => open(item.conversation_id)}>
                      {item.title}
                    </button>
                  </h3>
                  <p>
                    {item.message_count} ข้อความ · คลิปในคำถามล่าสุด:{' '}
                    {item.video_ids
                      .map((id) => videos.find((v) => v.video_id === id)?.title || id)
                      .join(' · ') || 'ยังไม่มีคลิป'}
                  </p>
                </div>
                <button
                  className="secondary"
                  disabled={locked}
                  onClick={() => open(item.conversation_id)}
                  aria-label={`เปิดบทสนทนา ${item.title}`}
                >
                  เปิดแชต ↗
                </button>
              </article>
            ))}
          </div>
          <nav className="history-pagination" aria-label="หน้าประวัติแชต">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>
              หน้าก่อนหน้า
            </button>
            <button
              disabled={offset + items.length >= total}
              onClick={() => setOffset(offset + 20)}
            >
              หน้าถัดไป
            </button>
          </nav>
        </>
      )}
    </section>
  );
}

import { useEffect, useRef, useState } from 'react';
import type { Api } from './api';
import type { Scope } from './types';

type Excerpt = {
  video_id: string;
  text: string;
  start_seconds: number;
  end_seconds: number;
  url: string;
  text_truncated?: boolean;
};
type SearchResult = {
  items: Excerpt[];
  notice: string;
  scan_complete?: boolean;
  inspected_segments?: number;
};
export default function LocalEvidenceSearch({
  api,
  question,
  scope,
}: {
  api: Api;
  question: string;
  scope: Scope;
}) {
  const [result, setResult] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const control = useRef<AbortController | null>(null);
  useEffect(() => () => control.current?.abort(), []);
  async function search() {
    if (busy) return;
    const c = new AbortController();
    control.current = c;
    setBusy(true);
    setError('');
    try {
      const response = await api.request<SearchResult>('/api/evidence/search', {
        method: 'POST',
        body: JSON.stringify({ question, scope }),
        signal: c.signal,
      });
      if (!c.signal.aborted) setResult(response.data);
    } catch {
      if (!c.signal.aborted) setError('ค้นข้อความไม่ได้ กรุณาลองอีกครั้ง');
    } finally {
      if (!c.signal.aborted) setBusy(false);
    }
  }
  return (
    <section aria-label="ค้นข้อความในคลิป">
      <button disabled={busy} onClick={() => void search()}>
        {busy ? 'กำลังค้นข้อความ…' : 'อ่านข้อความจากคลิปโดยไม่ใช้ AI'}
      </button>
      {error && <p role="alert">{error}</p>}
      {result && (
        <div role="status">
          <p>{result.notice}</p>
          {result.scan_complete === false && (
            <p>
              ค้นเพียงบางส่วนของบทถอดเสียง
              {result.inspected_segments !== undefined &&
                ` (${result.inspected_segments} ช่วงข้อความ)`}{' '}
              ผลนี้ยังไม่ครอบคลุมทั้งคลิป
            </p>
          )}
          {!result.items.length && <p>ไม่พบข้อความที่ตรงคำค้น ลองปรับคำค้นหรือเปิดบทถอดเสียง</p>}
          {result.items.map((item, i) => (
            <blockquote key={i}>
              <p>{item.text}</p>
              {item.text_truncated && <p>แสดงข้อความบางส่วน เปิดคลิปเพื่อดูเนื้อหาต่อ</p>}
              <a
                href={`https://www.youtube.com/watch?v=${encodeURIComponent(item.video_id)}&t=${Math.floor(item.start_seconds)}s`}
                target="_blank"
                rel="noreferrer"
              >
                เปิดคลิปที่ {Math.floor(item.start_seconds)} วินาที
              </a>
            </blockquote>
          ))}
        </div>
      )}
    </section>
  );
}

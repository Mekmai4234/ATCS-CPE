import { useEffect, useState } from 'react';
import { Api, ApiError } from './api';
export default function ChatPolicyNotice({ api }: { api: Api }) {
  const [notice, setNotice] = useState('');
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    void api
      .request<{ review_notice: string }>('/api/chat/policy', {
        signal: c.signal,
        cache: 'no-store',
      })
      .then(({ data }) => {
        if (!c.signal.aborted) {
          api.chatPolicyAvailable = true;
          setNotice(data.review_notice);
        }
      })
      .catch((error) => {
        if (c.signal.aborted) return;
        if (error instanceof ApiError && [404, 501].includes(error.status || 0))
          api.chatPolicyUnsupported = true;
        else {
          setFailed(true);
          setNotice('โหลดนโยบายแชทไม่สำเร็จ กรุณารีเฟรชก่อนส่งคำถาม');
        }
      });
    return () => {
      c.abort();
      api.chatPolicyAvailable = false;
    };
  }, [api]);
  return notice ? (
    <aside className="chat-policy-info" aria-label="ข้อมูลการใช้แชท">
      {failed ? (
        <p role="alert">{notice}</p>
      ) : (
        <details>
          <summary>ข้อมูลการใช้แชท</summary>
          <p>{notice}</p>
        </details>
      )}
    </aside>
  ) : null;
}

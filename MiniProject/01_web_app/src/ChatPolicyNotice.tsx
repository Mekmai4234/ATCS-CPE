import { useEffect, useState } from 'react';
import { Api, ApiError } from './api';
export default function ChatPolicyNotice({ api }: { api: Api }) {
  const [notice, setNotice] = useState('');
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
        else setNotice('โหลดนโยบายแชทไม่สำเร็จ กรุณารีเฟรชก่อนส่งคำถาม');
      });
    return () => {
      c.abort();
      api.chatPolicyAvailable = false;
    };
  }, [api]);
  return notice ? <p className="notice">{notice}</p> : null;
}

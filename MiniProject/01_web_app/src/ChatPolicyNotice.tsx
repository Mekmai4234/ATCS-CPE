import { useEffect, useState } from 'react';
import type { Api } from './api';
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
      .catch(() => {});
    return () => {
      c.abort();
      api.chatPolicyAvailable = false;
    };
  }, [api]);
  return notice ? <p className="notice">{notice}</p> : null;
}

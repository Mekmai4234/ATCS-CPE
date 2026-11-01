import { useEffect, useState } from 'react';
import { Api, ApiError } from './api';
import { serviceMessage } from './userMessages';

export type ProviderState = {
  selection: 'server_configuration';
  observed_at: string;
  execution?: { provider?: string; model?: string };
  local: { state: string; reason?: string | null };
  synthetic: boolean;
  loading_observed: boolean;
  regenerate: string[];
};
export default function ProviderStatus({
  api,
  onStatus,
}: {
  api: Api;
  onStatus: (value: ProviderState | null) => void;
}) {
  const [status, setStatus] = useState<ProviderState | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    setStatus(null);
    onStatus(null);
    setError('');
    setLoading(true);
    void api
      .request<ProviderState>('/api/providers', { signal: c.signal })
      .then(({ data }) => {
        if (c.signal.aborted) return;
        if (
          data.selection !== 'server_configuration' ||
          !data.local ||
          !Array.isArray(data.regenerate)
        )
          throw new Error('Unsupported provider contract');
        setStatus(data);
        onStatus(data);
      })
      .catch((reason) => {
        if (c.signal.aborted) return;
        if (!(reason instanceof ApiError && [404, 501].includes(reason.status || 0)))
          setError('ยังตรวจสถานะผู้ให้บริการไม่ได้ กรุณาลองใหม่');
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [api, onStatus, revision]);
  if (!status && !error) return null;
  const labels: Record<string, string> = {
    ready: 'บริการ AI ในเครื่องตอบสนอง และพบรุ่นโมเดลที่กำหนด',
    busy: 'คิว AI ในเครื่องเต็ม',
    unavailable: 'AI ในเครื่องยังไม่พร้อม',
    unverified: 'ยังยืนยันค่าตั้งต้น AI ในเครื่องไม่ได้',
    not_selected: 'ไม่ได้เลือก AI ในเครื่อง',
  };
  return (
    <section className="job-quota" aria-label="สถานะผู้ให้บริการ">
      {error && <p role="status">{error}</p>}
      {status && (
        <>
          <p>
            {status.synthetic ? 'สถานะจำลองสำหรับทดสอบ' : 'ผู้ให้บริการที่ระบบกำหนด'}:{' '}
            {status.execution?.provider === 'ollama'
              ? 'AI ในเครื่อง'
              : status.execution?.provider === 'gemini'
                ? 'Gemini'
                : 'ยังไม่ทราบ'}
          </p>
          <p>
            {labels[status.local.state] || 'ยังไม่มีข้อมูลสถานะนี้'} ·{' '}
            {serviceMessage(status.local.reason)}
          </p>
          {!status.loading_observed && <p>ยังตรวจสถานะโหลดโมเดลไม่ได้</p>}
          <p>
            ตรวจล่าสุด:{' '}
            {Number.isFinite(Date.parse(status.observed_at))
              ? new Date(status.observed_at).toLocaleString('th-TH')
              : 'ไม่มีเวลาที่ยืนยันได้'}{' '}
            · ไม่รับประกันสิทธิ์คำขอถัดไป
          </p>
        </>
      )}
      <button disabled={loading} onClick={() => setRevision((n) => n + 1)}>
        ตรวจผู้ให้บริการอีกครั้ง
      </button>
    </section>
  );
}

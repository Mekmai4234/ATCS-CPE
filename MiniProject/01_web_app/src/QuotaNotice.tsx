import { useEffect, useState } from 'react';
import type { Api } from './api';
import { retryTime } from './domain';

type Blocker = {
  reason: string;
  time_source: 'provider' | 'estimate';
  retry_at?: string;
  estimated_retry_at?: string;
};
type Quota = {
  accounting_source: 'local_ledger';
  provider_balance_verified: false;
  observed_at: string;
  scope: 'member' | 'project';
  status: 'waiting' | 'available' | 'unverified';
  pools: {
    bucket: string;
    usage: { requests_24h: number; requests_60s: number; tokens_60s: number };
    blockers: Blocker[];
  }[];
};
const reasons: Record<string, string> = {
  local_daily_limit: 'งบที่เว็บตั้งไว้: คำขอต่อวัน (RPD)',
  local_request_limit: 'งบที่เว็บตั้งไว้: คำขอต่อนาที (RPM)',
  local_token_limit: 'งบที่เว็บตั้งไว้: โทเคนต่อนาที (TPM)',
  member_request_limit: 'เพดานคำขอต่อนาทีของสมาชิก',
  local_concurrency_limit: 'คิวประมวลผลภายในเต็ม',
  local_counting_limit: 'เพดานนับโทเคนภายในเต็ม',
  member_counting_limit: 'เพดานนับโทเคนของสมาชิกเต็ม',
  provider_rate_limited: 'Google จำกัดการใช้งาน ยังไม่มีหลักฐานว่าเป็น RPM/TPM/RPD',
  provider_unavailable: 'ผู้ให้บริการประมวลผลยังไม่พร้อม',
};
export default function QuotaNotice({ api }: { api: Api }) {
  const [data, setData] = useState<Quota | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    setError('');
    // Discard an older balance immediately; never present stale success after an error.
    setData(null);
    void api
      .request<Quota>('/api/quota', { signal: c.signal })
      .then(({ data: value }) => {
        if (c.signal.aborted) return;
        if (
          value.accounting_source !== 'local_ledger' ||
          value.provider_balance_verified !== false ||
          !Array.isArray(value.pools)
        )
          throw new Error('Unsupported accounting source');
        setData(value);
      })
      .catch(() => {
        if (!c.signal.aborted) setError('ยังตรวจยอดภายในไม่ได้ กรุณาตรวจอีกครั้งก่อนส่งงานซ้ำ');
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [api, revision]);
  return (
    <details className="job-quota">
      <summary>ตรวจยอดใช้งานภายในระบบ</summary>
      <p>ยอดภายในเว็บ ไม่ใช่ยอดคงเหลือ Google และไม่รับประกันว่าคำขอถัดไปจะได้รับสิทธิ์</p>
      {loading && <p role="status">กำลังตรวจยอดภายใน…</p>}
      {error && <p role="status">{error}</p>}
      {data && (
        <>
          <p>
            แหล่งข้อมูล: บัญชีการใช้งานภายใน · ขอบเขต:{' '}
            {data.scope === 'member' ? 'สมาชิกนี้' : 'โปรเจกต์'}
          </p>
          <p>
            ตรวจล่าสุด:{' '}
            {Number.isFinite(Date.parse(data.observed_at))
              ? new Date(data.observed_at).toLocaleString('th-TH')
              : 'ไม่มีเวลาที่ตรวจสอบได้'}
          </p>
          {data.status === 'unverified' && (
            <p>นโยบายยังไม่ได้รับการยืนยัน ยังสรุปสิทธิ์ใช้งานไม่ได้</p>
          )}
          <ul>
            {data.pools.map((pool) => (
              <li key={pool.bucket}>
                <p>
                  {pool.bucket === 'embedding' ? 'การสร้างดัชนี' : 'การประมวลผล AI'} ·
                  ยอดภายในย้อนหลัง 24 ชั่วโมง: {pool.usage.requests_24h} คำขอ · 60 วินาที:{' '}
                  {pool.usage.requests_60s} คำขอ / {pool.usage.tokens_60s} โทเคน
                </p>
                {pool.blockers.map((blocker, index) => (
                  <p key={index}>
                    {reasons[blocker.reason] || 'ยังระบุประเภทข้อจำกัดไม่ได้'}
                    {retryTime(blocker) && <> · {retryTime(blocker)}</>}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        </>
      )}
      <button disabled={loading} onClick={() => setRevision((value) => value + 1)}>
        ตรวจยอดอีกครั้ง
      </button>
    </details>
  );
}

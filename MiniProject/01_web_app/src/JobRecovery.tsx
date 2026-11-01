import { useEffect, useRef, useState } from 'react';
import { Api, ApiError } from './api';
import { jobStatus, terminal } from './domain';
import type { Job, RecoverableJob } from './types';

export default function JobRecovery({
  api,
  restore,
  locked,
  hasPending = false,
  liveJobs,
  videoTitles = {},
}: {
  api: Api;
  restore: (job: RecoverableJob) => void;
  locked: boolean;
  hasPending?: boolean;
  liveJobs?: Job[];
  videoTitles?: Record<string, string>;
}) {
  const [jobs, setJobs] = useState<RecoverableJob[]>([]);
  const current = useRef(jobs);
  current.current = jobs;
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [older, setOlder] = useState(false);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [worker, setWorker] = useState<boolean>();
  const [resuming, setResuming] = useState<string | null>(null);
  const label = (job: RecoverableJob) =>
    job.request.question ||
    job.request.goal ||
    job.request.topic ||
    job.request.instruction ||
    (job.kind === 'quiz_grade'
      ? 'ตรวจแบบทดสอบ'
      : job.kind === 'import'
        ? `นำเข้าคลิป · ${videoTitles[job.video_id || ''] || job.video_id || ''}`
        : {
            chat: 'แชต',
            analysis: 'สรุปและเปรียบเทียบ',
            research: 'ค้นคว้า',
            artifact: 'แบบฝึกหัด',
            enrich: 'ภาพและ OCR',
          }[job.kind] || 'งานที่บันทึกไว้');
  useEffect(() => {
    if (!liveJobs?.length) return;
    setJobs((previous) =>
      previous.map((job) => {
        const live = liveJobs.find((item) => item.job_id === job.job_id);
        return live ? { ...job, ...live } : job;
      }),
    );
  }, [liveJobs]);
  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    setError('');
    void (async () => {
      let cursor = 0;
      const active: RecoverableJob[] = [];
      do {
        const data = await api.memberJobs(false, cursor, c.signal);
        active.push(...data.items);
        cursor += data.items.length;
        if (!data.items.length || cursor >= data.total) break;
      } while (!c.signal.aborted);
      const recent = await api.memberJobs(true, older ? offset : 0, c.signal, older ? 50 : 5);
      const ids = new Set([...active, ...recent.items].map((job) => job.job_id));
      const stale = current.current.filter((job) => !terminal(job.state) && !ids.has(job.job_id));
      const updated = await Promise.all(
        stale.map(async (job) => ({ ...job, ...(await api.job(job.job_id, c.signal)) })),
      );
      if (c.signal.aborted) return;
      setJobs((previous) => [
        ...new Map(
          [...previous, ...active, ...recent.items, ...updated].map((job) => [job.job_id, job]),
        ).values(),
      ]);
      setHasMore(older && offset + recent.items.length < recent.total);
    })()
      .catch((reason) => {
        if (
          !c.signal.aborted &&
          !(reason instanceof ApiError && [404, 501].includes(reason.status || 0))
        )
          setError('โหลดงานเดิมไม่ได้ กรุณาตรวจสอบก่อนส่งงานซ้ำ');
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [api, revision, older, offset]);
  const visible = [...jobs]
    .sort((a, b) => Date.parse(b.created_at || '') - Date.parse(a.created_at || ''))
    .filter((job) =>
      ['chat', 'analysis', 'research', 'artifact', 'import', 'enrich', 'quiz_grade'].includes(
        job.kind,
      ),
    );
  const priority: Record<string, number> = { running: 0, queued: 1, paused: 2 };
  const active = visible
    .filter((job) => !terminal(job.state))
    .sort(
      (a, b) =>
        (priority[a.state] ?? 3) - (priority[b.state] ?? 3) ||
        Date.parse(a.created_at || '') - Date.parse(b.created_at || ''),
    );
  const running = active.filter((job) => job.state === 'running');
  const queued = active.filter((job) => job.state === 'queued');
  const paused = active.filter((job) => job.state === 'paused');
  const latestDone = visible.find((job) => ['completed', 'partial'].includes(job.state));
  useEffect(() => {
    if (loading) return;
    const timer = setTimeout(
      () => setRevision((n) => n + 1),
      hasPending || running.length || queued.length ? 5000 : 15000,
    );
    return () => clearTimeout(timer);
  }, [loading, revision, hasPending, running.length, queued.length]);
  useEffect(() => {
    const c = new AbortController();
    const check = () =>
      void api
        .workerStatus(c.signal)
        .then((value) => {
          if (!c.signal.aborted) setWorker(value.ready);
        })
        .catch(() => {});
    check();
    const timer = setInterval(check, 15000);
    return () => {
      c.abort();
      clearInterval(timer);
    };
  }, [api]);
  async function resume(job: RecoverableJob) {
    setResuming(job.job_id);
    setError('');
    try {
      const accepted =
        job.kind === 'import' || job.kind === 'enrich'
          ? await api.retry(job.job_id)
          : job.kind === 'chat'
            ? await api.resumeChat(job.job_id, job.request, (message) => window.confirm(message))
            : (
                await api.request<{ job_id: string }>(
                  `/api/jobs/${encodeURIComponent(job.job_id)}/resume`,
                  { method: 'POST', body: '{}' },
                )
              ).data;
      if (!accepted) return;
      const fresh = await api.job(accepted.job_id);
      setJobs((previous) => previous.filter((item) => item.job_id !== job.job_id));
      restore({ ...job, ...fresh });
      setRevision((n) => n + 1);
    } catch (reason) {
      setError(
        reason instanceof ApiError && reason.code === 'quota_unavailable'
          ? 'ยังรอโควตา งานเดิมถูกเก็บไว้แล้ว กรุณารอเวลาที่แจ้ง'
          : 'ยังทำงานต่อไม่ได้ กรุณาลองใหม่ภายหลัง',
      );
    } finally {
      setResuming(null);
    }
  }
  const open = (job: RecoverableJob) => {
    if (job.state === 'paused') {
      setOlder(true);
      return;
    }
    restore(job);
  };
  return (
    <section className="recovery-panel" aria-label="งานของฉัน">
      <div className="work-status-strip" role="region" aria-label="ติดตามงาน">
        <div role="status">
          <strong>
            {running.length
              ? 'กำลังทำงาน'
              : queued.length
                ? 'มีงานรอคิว'
                : paused.length
                  ? 'มีงานพักรอ'
                  : hasPending
                    ? 'กำลังส่งงาน'
                    : 'พร้อมเรียนรู้'}
          </strong>
          <span>
            กำลังทำ {running.length} · รอคิว {queued.length} · พักรอ {paused.length}
          </span>
        </div>
        {!!(running.length || queued.length || hasPending) && (
          <progress aria-label="งานกำลังประมวลผล" />
        )}
        {active.slice(0, 1).map((job) => (
          <div className="work-status-item" key={job.job_id}>
            <span>
              {label(job)}
              <small>
                {jobStatus(job)}
                {job.wait?.retry_at || job.wait?.estimated_retry_at
                  ? ` · พร้อมประมาณ ${new Date((job.wait.retry_at || job.wait.estimated_retry_at)!).toLocaleString('th-TH')}`
                  : ''}
              </small>
            </span>
            <button className="secondary" disabled={locked} onClick={() => open(job)}>
              ดูงาน
            </button>
          </div>
        ))}
        {!active.length && latestDone && (
          <div className="work-status-item">
            <span>
              ล่าสุด · {label(latestDone)}
              <small>{jobStatus(latestDone)}</small>
            </span>
            <button className="secondary" disabled={locked} onClick={() => restore(latestDone)}>
              ดูงานล่าสุด
            </button>
          </div>
        )}
      </div>
      <div className="recovery-tools">
        <button
          className="text-button"
          disabled={loading || locked}
          onClick={() => {
            setOlder(true);
            setOffset(0);
            setRevision((n) => n + 1);
          }}
        >
          งานที่ผ่านมา
        </button>
        {loading && <small role="status">กำลังตรวจงานเดิม…</small>}
      </div>
      {error && (
        <p role="alert">
          {error} <button onClick={() => setRevision((n) => n + 1)}>ลองโหลดงานอีกครั้ง</button>
        </p>
      )}
      {worker === false && (hasPending || active.length > 0) && (
        <p className="notice warning" role="status">
          ตัวประมวลผลยังไม่พร้อม งานถูกเก็บไว้แล้ว กรุณารอก่อนส่งซ้ำ
        </p>
      )}
      {(older || active.length > 0) && visible.length > 0 && (
        <details>
          <summary>งานที่บันทึกไว้ {visible.length} รายการ</summary>
          <div className="recovered-jobs">
            {(older ? visible : active).map((job) => (
              <article key={job.job_id}>
                <div>
                  <strong>{label(job)}</strong>
                  <p>{jobStatus(job)}</p>
                  {(job.wait?.retry_at || job.wait?.estimated_retry_at) && (
                    <small>
                      พร้อมประมาณ{' '}
                      {new Date((job.wait.retry_at || job.wait.estimated_retry_at)!).toLocaleString(
                        'th-TH',
                      )}
                    </small>
                  )}
                </div>
                {job.retryable && ['failed', 'paused'].includes(job.state) && (
                  <button
                    className="primary"
                    disabled={locked || !!resuming}
                    onClick={() => void resume(job)}
                  >
                    {resuming === job.job_id ? 'กำลังทำต่อ…' : 'ทำงานนี้ต่อ'}
                  </button>
                )}
                <button className="secondary" disabled={locked} onClick={() => open(job)}>
                  {terminal(job.state) ? 'เปิดผลลัพธ์' : 'ติดตามงานเดิม'}
                </button>
              </article>
            ))}
          </div>
          {hasMore && (
            <button disabled={loading} onClick={() => setOffset((n) => n + 50)}>
              โหลดงานเพิ่มเติม
            </button>
          )}
        </details>
      )}
    </section>
  );
}

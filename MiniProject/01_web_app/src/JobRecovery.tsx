import { useCallback, useEffect, useState } from 'react';
import { Api, ApiError } from './api';
import { jobStatus, terminal } from './domain';
import type { RecoverableJob } from './types';

export default function JobRecovery({
  api,
  restore,
  locked,
  hasPending = false,
}: {
  api: Api;
  restore: (job: RecoverableJob) => void;
  locked: boolean;
  hasPending?: boolean;
}) {
  const [jobs, setJobs] = useState<RecoverableJob[]>([]);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [older, setOlder] = useState(false);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [worker, setWorker] = useState<boolean>();
  const [loading, setLoading] = useState(true);
  const merge = useCallback(
    (items: RecoverableJob[]) =>
      setJobs((previous) => [
        ...new Map([...previous, ...items].map((item) => [item.job_id, item])).values(),
      ]),
    [],
  );
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    void (async () => {
      let cursor = older ? offset : 0;
      do {
        const data = await api.memberJobs(older, cursor, controller.signal);
        if (controller.signal.aborted) return;
        merge(data.items);
        setHasMore(older && cursor + data.items.length < data.total);
        cursor += data.items.length;
        if (older || !data.items.length || cursor >= data.total) break;
      } while (!controller.signal.aborted);
    })()
      .catch((reason) => {
        if (
          !controller.signal.aborted &&
          !(reason instanceof ApiError && [404, 501].includes(reason.status || 0))
        )
          setError('โหลดงานเดิมไม่ได้ กรุณาตรวจสอบก่อนส่งงานซ้ำ');
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [api, older, offset, attempt, merge]);
  useEffect(() => {
    const controller = new AbortController();
    const check = () =>
      void api
        .workerStatus(controller.signal)
        .then((value) => {
          if (!controller.signal.aborted) setWorker(value.ready);
        })
        .catch(() => {});
    check();
    const timer = setInterval(check, 15000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [api]);
  const visible = jobs.filter((job) =>
    ['chat', 'analysis', 'research', 'artifact', 'import', 'enrich'].includes(job.kind),
  );
  return (
    <section className="recovery-panel" aria-label="งานของฉัน">
      <div className="recovery-tools">
        <button
          className="text-button"
          disabled={loading || locked}
          onClick={() => {
            setOlder(true);
            setOffset(0);
            setAttempt((n) => n + 1);
          }}
        >
          งานที่ผ่านมา
        </button>
        {loading && <small role="status">กำลังตรวจงานเดิม…</small>}
      </div>
      {error && (
        <p role="alert">
          {error} <button onClick={() => setAttempt((n) => n + 1)}>ลองโหลดงานอีกครั้ง</button>
        </p>
      )}
      {worker === false && (hasPending || visible.some((job) => !terminal(job.state))) && (
        <p className="notice warning" role="status">
          ตัวประมวลผลยังไม่พร้อม งานถูกเก็บไว้แล้ว กรุณารอก่อนส่งซ้ำ
        </p>
      )}
      {visible.length > 0 && (
        <details open={!older}>
          <summary>งานที่บันทึกไว้ {visible.length} รายการ</summary>
          <div className="recovered-jobs">
            {visible.map((job) => (
              <article key={job.job_id}>
                <div>
                  <strong>
                    {job.request.question ||
                      job.request.goal ||
                      job.request.topic ||
                      job.request.instruction ||
                      {
                        chat: 'แชต',
                        analysis: 'สรุปและเปรียบเทียบ',
                        research: 'ค้นคว้า',
                        artifact: 'แบบฝึกหัด',
                        import: 'นำเข้าคลิป',
                        enrich: 'ภาพและ OCR',
                      }[job.kind] ||
                      'งานที่บันทึกไว้'}
                  </strong>
                  <p>{jobStatus(job)}</p>
                </div>
                <button
                  className="secondary"
                  disabled={locked}
                  onClick={() => {
                    setJobs((items) => items.filter((item) => item.job_id !== job.job_id));
                    restore(job);
                  }}
                >
                  {terminal(job.state) ? 'เปิดผลลัพธ์' : 'ติดตามงานเดิม'}
                </button>
              </article>
            ))}
          </div>
          {hasMore && (
            <button disabled={loading} onClick={() => setOffset((value) => value + 50)}>
              โหลดงานเพิ่มเติม
            </button>
          )}
        </details>
      )}
    </section>
  );
}

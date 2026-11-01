import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Api, ApiError } from './api';
import { jobStatus, retryTime, terminal } from './domain';
import type { Job, RecoverableJob } from './types';
import { UiIcon } from './Visuals';
import QuotaNotice from './QuotaNotice';

function WorkIcon({ name }: { name: 'list' | 'pause' | 'close' | 'check' | 'clock' }) {
  const paths = {
    list: 'm3 5 2 2 3-4 M11 6h10 M3 12h4 M11 12h10 M3 18h4 M11 18h10',
    pause: 'M9 8v8 M15 8v8',
    close: 'm6 6 12 12 M6 18 18 6',
    check: 'm7 12 3 3 7-7',
    clock: 'M12 7v6l4 2',
  };
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {!['list', 'close'].includes(name) && <circle cx="12" cy="12" r="9" />}
      <path d={paths[name]} />
    </svg>
  );
}
const stateNames: Record<string, string> = {
  running: 'กำลังทำ',
  queued: 'รอคิว',
  paused: 'พักรอ',
  completed: 'เสร็จแล้ว',
  partial: 'ได้ผลบางส่วน',
  failed: 'ไม่สำเร็จ',
  cancelled: 'ยกเลิกแล้ว',
};
function typeName(job: RecoverableJob) {
  const task = {
    summary: 'สรุปวิดีโอ',
    compare: 'เปรียบเทียบคลิป',
    quiz: 'แบบทดสอบ',
    flashcards: 'แฟลชการ์ด',
    study_plan: 'แผนเรียน',
  };
  return (
    (job.request.type && task[job.request.type as keyof typeof task]) ||
    {
      chat: 'แชทกับ Buddy',
      analysis: 'สรุปและเปรียบเทียบ',
      research: 'ค้นคว้า',
      artifact: 'แบบฝึกหัด',
      import: 'นำเข้าวิดีโอ',
      enrich: 'ภาพและ OCR',
      quiz_grade: 'ตรวจแบบทดสอบ',
    }[job.kind] ||
    'งานที่บันทึกไว้'
  );
}
function waitMessage(job: RecoverableJob) {
  return retryTime(job.wait || {}, job.presentation?.retryAt);
}
function quotaPaused(job: RecoverableJob) {
  return (
    job.state === 'paused' &&
    (job.error_code === 'quota_wait' ||
      job.wait?.reason === 'quota_wait' ||
      job.presentation?.stage === 'quota_paused')
  );
}

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
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [historyRevision, setHistoryRevision] = useState(0);
  const [resumeError, setResumeError] = useState('');
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [older, setOlder] = useState(false);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [worker, setWorker] = useState<boolean>();
  const [resuming, setResuming] = useState<string | null>(null);
  const incomingIds = liveJobs?.map((job) => job.job_id).join(',') || '';
  useEffect(() => {
    if (incomingIds) setRevision((n) => n + 1);
  }, [incomingIds]);
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
      const recent = await api.memberJobs(true, 0, c.signal, 5);
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
  }, [api, revision]);
  useEffect(() => {
    if (!drawerOpen || !older) return;
    const c = new AbortController();
    setHistoryLoading(true);
    setHistoryError('');
    void api
      .memberJobs(true, offset, c.signal, 50)
      .then((page) => {
        if (c.signal.aborted) return;
        setJobs((previous) => [
          ...new Map([...previous, ...page.items].map((job) => [job.job_id, job])).values(),
        ]);
        setHasMore(offset + page.items.length < page.total && page.items.length > 0);
      })
      .catch(() => {
        if (!c.signal.aborted) setHistoryError('โหลดประวัติไม่ได้ กรุณาลองอีกครั้ง');
      })
      .finally(() => {
        if (!c.signal.aborted) setHistoryLoading(false);
      });
    return () => c.abort();
  }, [api, drawerOpen, older, offset, historyRevision]);
  useEffect(() => {
    if (!drawerOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [drawerOpen]);
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
      hasPending || running.length || queued.length
        ? 5000
        : paused.length || drawerOpen
          ? 15000
          : 60000,
    );
    return () => clearTimeout(timer);
  }, [loading, revision, hasPending, running.length, queued.length, paused.length, drawerOpen]);
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
    const timer = setInterval(check, hasPending || running.length || queued.length ? 15000 : 60000);
    return () => {
      c.abort();
      clearInterval(timer);
    };
  }, [api, hasPending, running.length, queued.length]);
  async function resume(job: RecoverableJob) {
    setResuming(job.job_id);
    setResumeError('');
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
      closeDrawer();
      restore({ ...job, ...fresh });
      setRevision((n) => n + 1);
    } catch (reason) {
      setResumeError(
        reason instanceof ApiError &&
          ['quota_unavailable', 'quota_wait', 'provider_wait'].includes(reason.code || '')
          ? 'ยังรอโควตา งานเดิมถูกเก็บไว้แล้ว กรุณารอเวลาที่แจ้ง'
          : 'ยังทำงานต่อไม่ได้ กรุณาลองใหม่ภายหลัง',
      );
    } finally {
      setResuming(null);
    }
  }
  function closeDrawer() {
    dialog.current?.close();
    setDrawerOpen(false);
  }
  function openDrawer() {
    setOlder(false);
    setOffset(0);
    setDrawerOpen(true);
    dialog.current?.showModal();
  }
  function selectTab(history: boolean, focus = false) {
    setOlder(history);
    if (focus) document.getElementById(`${id}-${history ? 'history' : 'active'}`)?.focus();
  }
  function tabKeys(event: KeyboardEvent<HTMLDivElement>) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    selectTab(event.key === 'Home' ? false : event.key === 'End' ? true : !older, true);
  }
  function open(job: RecoverableJob) {
    closeDrawer();
    restore(job);
  }
  const history = visible.filter((job) => terminal(job.state));
  const list = older ? history : active;
  const quotaJobs = paused.filter(quotaPaused);
  const allQuota = active.length > 0 && quotaJobs.length === active.length;
  const quotaTimes = [...new Set(quotaJobs.map(waitMessage).filter(Boolean))];
  const statusIcon = (state: string) =>
    state === 'paused' ? 'pause' : state === 'completed' ? 'check' : 'clock';
  return (
    <section className="job-recovery" aria-label="งานของฉัน">
      <div className="job-status-strip" role="region" aria-label="ติดตามงาน">
        <div className="job-strip-icon">
          <WorkIcon name="list" />
        </div>
        <div className="job-strip-copy">
          <h2>งานของฉัน</h2>
          <div className="job-strip-summary" role="status" aria-atomic="true">
            {error ? (
              <span className="job-status-badge is-failed">ตรวจสถานะงานไม่ได้</span>
            ) : (
              <>
                {[
                  [running, 'running'],
                  [queued, 'queued'],
                  [paused, 'paused'],
                ].map(([items, state]) => {
                  const count = (items as RecoverableJob[]).length;
                  return (
                    count > 0 && (
                      <span
                        className="job-status-badge"
                        data-state={state as string}
                        key={state as string}
                      >
                        <WorkIcon name={statusIcon(state as string)} />
                        {stateNames[state as string]} {count}
                        {active.length === count ? ' งาน' : ''}
                      </span>
                    )
                  );
                })}
                {!active.length && (
                  <span className="job-status-badge">
                    {loading && !jobs.length
                      ? 'กำลังตรวจสถานะ…'
                      : hasPending
                        ? 'กำลังส่งงาน…'
                        : latestDone
                          ? 'มีผลลัพธ์พร้อมดู'
                          : 'ไม่มีงานค้าง'}
                  </span>
                )}
                {paused.length > 0 && !running.length && !queued.length && (
                  <span className="job-strip-hint">บันทึกงานไว้แล้ว</span>
                )}
              </>
            )}
          </div>
        </div>
        <button
          className="job-open-button"
          ref={trigger}
          aria-haspopup="dialog"
          onClick={openDrawer}
        >
          ดูงานทั้งหมด
          <UiIcon name="arrow" />
        </button>
      </div>
      <dialog
        className="job-drawer"
        ref={dialog}
        aria-labelledby={`${id}-title`}
        onClose={() => {
          setDrawerOpen(false);
          trigger.current?.focus();
        }}
        onClick={(event) => {
          if (
            event.target === event.currentTarget &&
            event.clientX < event.currentTarget.getBoundingClientRect().left
          )
            closeDrawer();
        }}
      >
        <div className="job-drawer-layout">
          <header className="job-drawer-header">
            <div>
              <h2 id={`${id}-title`}>งานของฉัน</h2>
              <p>ติดตามงานและเปิดผลลัพธ์ได้ที่นี่</p>
            </div>
            <button className="job-drawer-close" aria-label="ปิดงานของฉัน" onClick={closeDrawer}>
              <WorkIcon name="close" />
            </button>
          </header>
          <div
            className="job-drawer-tabs"
            role="tablist"
            aria-label="รายการงาน"
            onKeyDown={tabKeys}
          >
            <button
              id={`${id}-active`}
              role="tab"
              aria-selected={!older}
              aria-controls={`${id}-panel`}
              tabIndex={older ? -1 : 0}
              onClick={() => selectTab(false)}
            >
              กำลังดำเนินการ {active.length > 0 && <span>{active.length}</span>}
            </button>
            <button
              id={`${id}-history`}
              role="tab"
              aria-selected={older}
              aria-controls={`${id}-panel`}
              tabIndex={older ? 0 : -1}
              onClick={() => selectTab(true)}
            >
              ประวัติ
            </button>
          </div>
          <div
            className="job-drawer-body"
            id={`${id}-panel`}
            role="tabpanel"
            aria-labelledby={`${id}-${older ? 'history' : 'active'}`}
            tabIndex={0}
          >
            {(error || (older && historyError) || resumeError) && (
              <div className="job-drawer-notice is-error" role="alert">
                <div>
                  <strong>{resumeError || (older && historyError) || error}</strong>
                  {!resumeError && (
                    <button
                      className="job-card-action"
                      onClick={() => {
                        setRevision((n) => n + 1);
                        setHistoryRevision((n) => n + 1);
                      }}
                    >
                      ลองอีกครั้ง
                    </button>
                  )}
                </div>
              </div>
            )}
            {!older && worker === false && (hasPending || active.length > 0) && (
              <div className="job-drawer-notice" role="status">
                <WorkIcon name="clock" />
                <div>
                  <strong>ตัวประมวลผลยังไม่พร้อม</strong>
                  <p>บันทึกงานไว้แล้ว กรุณารอก่อนส่งซ้ำ</p>
                </div>
              </div>
            )}
            {!older && allQuota && (
              <div className="job-drawer-notice">
                <WorkIcon name="clock" />
                <div>
                  <strong>งบการใช้งานภายในเว็บเต็ม</strong>
                  <p>
                    {quotaTimes.length === 1
                      ? quotaTimes[0]
                      : 'รอระบบพร้อม แล้วกดทำต่อที่งานของคุณ'}
                    <br />
                    งานและคำตอบของคุณยังอยู่ครบ
                  </p>
                </div>
              </div>
            )}
            {drawerOpen && <QuotaNotice api={api} />}
            {older && historyLoading && (
              <p role="status" className="job-card-description">
                กำลังโหลดประวัติ…
              </p>
            )}
            <div className="job-list">
              {list.map((job) => {
                const quota = quotaPaused(job);
                const providerAt =
                  job.wait?.time_source === 'provider' ? job.wait.retry_at : undefined;
                const notYet = !!providerAt && Date.parse(providerAt) > Date.now();
                const canRestore = ['completed', 'partial', 'running', 'queued'].includes(
                  job.state,
                );
                const canResume = job.retryable && ['failed', 'paused'].includes(job.state);
                return (
                  <article key={job.job_id} className="job-card">
                    <div className="job-card-type">
                      <UiIcon
                        name={
                          job.kind === 'chat'
                            ? 'chat'
                            : job.kind === 'quiz_grade' || job.kind === 'artifact'
                              ? 'learn'
                              : 'library'
                        }
                      />
                      {typeName(job)}
                    </div>
                    <h3 className="job-card-title">{label(job)}</h3>
                    {quota ? (
                      <p className="job-card-description">
                        {allQuota && quotaTimes.length === 1
                          ? 'บันทึกงานไว้แล้ว'
                          : `รอสิทธิ์ใช้งานเพิ่มเติม${waitMessage(job) ? ' · ' + waitMessage(job) : ''}`}
                      </p>
                    ) : (
                      <p className="job-card-description">{jobStatus(job)}</p>
                    )}
                    <div className="job-card-bottom">
                      <span className="job-card-status" data-state={job.state}>
                        <WorkIcon name={statusIcon(job.state)} />
                        {stateNames[job.state]}
                      </span>
                      <div className="job-card-actions">
                        {canResume && (
                          <button
                            className="job-card-action"
                            disabled={locked || !!resuming || notYet}
                            onClick={() => void resume(job)}
                          >
                            {resuming === job.job_id
                              ? 'กำลังทำต่อ…'
                              : notYet
                                ? 'ทำต่อเมื่อพร้อม'
                                : job.state === 'failed'
                                  ? job.error_code === 'quota_wait'
                                    ? 'ตรวจโควตาและทำต่อ'
                                    : 'ลองใหม่'
                                  : 'ทำต่อ'}
                          </button>
                        )}
                        {canRestore && (
                          <button
                            className="job-card-action"
                            disabled={locked || !!resuming}
                            onClick={() => open(job)}
                          >
                            {terminal(job.state) ? 'ดูผลลัพธ์' : 'ติดตามงาน'}
                            <UiIcon name="arrow" />
                          </button>
                        )}
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
            {!list.length && !(older ? historyLoading || historyError : loading || error) && (
              <div className="job-empty">
                <WorkIcon name="check" />
                {older ? 'ยังไม่มีประวัติงาน' : 'ไม่มีงานค้าง'}
                {!older && history.length > 0 && <p>ดูงานที่เสร็จแล้วได้ในประวัติ</p>}
              </div>
            )}
            {older && hasMore && (
              <button
                className="job-load-more"
                disabled={historyLoading}
                onClick={() => setOffset((n) => n + 50)}
              >
                โหลดงานเพิ่มเติม
              </button>
            )}
          </div>
        </div>
      </dialog>
    </section>
  );
}

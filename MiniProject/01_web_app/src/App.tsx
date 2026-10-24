import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Api, ApiError, pollJob } from './api';
import { buildScope, jobWarning, statusLabels, terminal, videoIdFromUrl } from './domain';
import { demoTransport } from './demo';
import { ResultView } from './Results';
import { reconcileSources, snapshotSources, sourceKey } from './sources';
import type { SourceSnapshot } from './types';
import type { ImportItem, Job, ProgressEvent, TaskResult, TaskType, Video } from './types';
import type { Member } from './session';
import { BuddyLogo, ForestBackdrop } from './Forest';
import HomeHero from './HomeHero';
import FloatingBuddy from './FloatingBuddy';
import { scopeFingerprint } from './buddyModel';

type WorkspaceView = 'home' | 'library' | 'chat' | 'learn';
interface WorkspaceProps {
  api?: Api;
  member?: Member;
  initialView?: WorkspaceView;
  onNavigate?: (path: string) => void;
  onLogout?: () => void;
  adminEnabled?: boolean;
}

const demo = import.meta.env.VITE_DEMO_MODE === 'true';
const taskNames: Record<TaskType, string> = {
  chat: 'ถามจากคลิป',
  summary: 'สรุปเนื้อหา',
  compare: 'เปรียบเทียบคลิป',
  research: 'ค้นคว้าหลายขั้นตอน',
  quiz: 'แบบทดสอบ',
  flashcards: 'แฟลชการ์ด',
  study_plan: 'แผนเรียน',
};
interface Operation {
  key: string;
  path: string;
  payload: object;
  label: string;
  type: TaskType;
  jobId?: string;
  sources: SourceSnapshot[];
}
interface Turn {
  type?: TaskType;
  id: string;
  label: string;
  result: TaskResult;
  partial: boolean;
  jobId?: string;
  sources: SourceSnapshot[];
}
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : 'เกิดข้อผิดพลาด กรุณาลองอีกครั้ง';
const aborted = (error: unknown) => error instanceof DOMException && error.name === 'AbortError';

function Icon({ name }: { name: 'library' | 'chat' | 'learn' | 'plus' | 'arrow' }) {
  const paths = {
    library: 'M4 5h6v14H4z M14 5h6v14h-6z',
    chat: 'M4 4h16v12H9l-5 4z',
    learn: 'm2 8 10-5 10 5-10 5z M6 10v7l6 3 6-3v-7',
    plus: 'M12 5v14 M5 12h14',
    arrow: 'M5 12h14 m-6-6 6 6-6 6',
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
      <path d={paths[name]} />
    </svg>
  );
}

function DeleteDialog({ cancel, confirm }: { cancel: () => void; confirm: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog ref={ref} className="modal" aria-labelledby="delete-title" onCancel={cancel}>
      <h2 id="delete-title">ลบคลิปออกจากคลัง?</h2>
      <p>
        คลิปนี้จะไม่ถูกใช้เป็นแหล่งข้อมูลในคลังของคุณอีก ประวัติคำตอบเดิมยังอยู่
        แต่หลักฐานของคลิปนี้จะใช้ไม่ได้
      </p>
      <div>
        <button autoFocus className="secondary" onClick={cancel}>
          เก็บคลิปไว้
        </button>
        <button className="danger" onClick={confirm}>
          ยืนยันลบคลิป
        </button>
      </div>
    </dialog>
  );
}

function Thumbnail({ url }: { url: string | null }) {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (
      parsed.protocol !== 'https:' ||
      !(parsed.hostname === 'ytimg.com' || parsed.hostname.endsWith('.ytimg.com'))
    )
      return null;
  } catch {
    return null;
  }
  return (
    <img
      className="video-thumbnail"
      src={url}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={(e) => {
        e.currentTarget.hidden = true;
      }}
    />
  );
}

export default function App({
  api: suppliedApi,
  member,
  initialView = 'library',
  onNavigate,
  onLogout,
  adminEnabled = false,
}: WorkspaceProps = {}) {
  const api = useMemo(
    () =>
      suppliedApi ||
      new Api(import.meta.env.NEXT_PUBLIC_API_BASE_URL, demo ? demoTransport() : undefined),
    [suppliedApi],
  );
  const [mode, setMode] = useState(demo ? 'fixture' : 'unknown');
  api.onMode = setMode;
  const [tab, setTab] = useState<WorkspaceView>(initialView);
  useEffect(() => {
    setTab(initialView);
  }, [initialView]);
  function navigateTab(view: WorkspaceView) {
    setTab(view);
    onNavigate?.(view === 'home' ? '/' : view === 'learn' ? '/learning' : `/${view}`);
  }
  const [videos, setVideos] = useState<Video[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [libraryError, setLibraryError] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [channel, setChannel] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [urls, setUrls] = useState('');
  const [importing, setImporting] = useState(false);
  const [imports, setImports] = useState<{ url: string; item: ImportItem }[]>([]);
  const [importError, setImportError] = useState('');
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [watchErrors, setWatchErrors] = useState<Record<string, string>>({});
  const [question, setQuestion] = useState('');
  const [taskType, setTaskType] = useState<TaskType>('summary');
  const [days, setDays] = useState(7);
  const [level, setLevel] = useState('beginner');
  const [conversation, setConversation] = useState<string | null>(null);
  const conversationId = useRef<string | null>(null);
  const conversationScope = useRef('');
  const [scopeNotice, setScopeNotice] = useState('');
  const [historyPending, setHistoryPending] = useState(false);
  const [buddyOpen, setBuddyOpen] = useState(false);
  const [buddyHidden, setBuddyHidden] = useState(false);
  const buddyRestore = useRef<HTMLButtonElement>(null);
  const followResults = useRef(true);
  const resultsViewport = useRef<HTMLDivElement>(null);
  const [newResults, setNewResults] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const turnsRef = useRef<Turn[]>([]);
  const inventory = useRef<{ videos: Video[]; completeInventory: boolean }>({
    videos: [],
    completeInventory: false,
  });
  const retiredSources = useRef(new Set<string>());
  const libraryRevisions = useRef(new Map<string, number>());
  const [sourceCheckError, setSourceCheckError] = useState('');
  function updateTurns(update: (previous: Turn[]) => Turn[]) {
    turnsRef.current = update(turnsRef.current);
    setTurns(turnsRef.current);
  }
  const [operation, setOperation] = useState<Operation | null>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [taskError, setTaskError] = useState('');
  const [canRetry, setCanRetry] = useState(false);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [actionError, setActionError] = useState('');
  const watchers = useRef(new Map<string, AbortController>());
  const requests = useRef(new Set<AbortController>());
  const refreshSequence = useRef(0);
  const pageCount = useRef(1);
  const alive = useRef(true);
  const operationRef = useRef<Operation | null>(null);
  const resultsEnd = useRef<HTMLDivElement>(null);

  const newRequest = () => {
    const controller = new AbortController();
    requests.current.add(controller);
    return controller;
  };
  async function refresh(pages = pageCount.current) {
    const sequence = ++refreshSequence.current;
    const controller = newRequest();
    setLoading(true);
    try {
      let all: Video[] = [];
      let count = 0;
      for (let page = 0; page < pages; page++) {
        const data = await api.videos(page * 50, controller.signal);
        all = [...all, ...data.items];
        count = data.total;
        if (all.length >= count) break;
      }
      if (sequence !== refreshSequence.current || !alive.current) return;
      setVideos(all);
      setTotal(count);
      setLibraryError('');
      pageCount.current = pages;
      setSelected((ids) =>
        ids.filter((id) => all.some((v) => v.video_id === id && v.status === 'ready')),
      );
      inventory.current = { videos: all, completeInventory: all.length >= count };
      // Revalidate stored job identity, not merely the presence of a video ID.
      const historical = turnsRef.current.filter((turn) => turn.jobId);
      const checks = await Promise.allSettled(
        historical.map((turn) => api.job(turn.jobId!, controller.signal)),
      );
      if (sequence !== refreshSequence.current || !alive.current) return;
      const availability = new Map<string, boolean | undefined>();
      checks.forEach((check, index) => {
        if (check.status === 'fulfilled')
          availability.set(historical[index].id, check.value.sources_available);
      });
      setSourceCheckError(
        checks.some((check) => check.status === 'rejected')
          ? 'ตรวจสอบสถานะแหล่งข้อมูลของผลเก่าไม่ครบ กรุณารีเฟรชอีกครั้ง'
          : '',
      );
      updateTurns((previous) =>
        previous.map((turn) => ({
          ...turn,
          result: reconcileSources(turn.result, turn.sources, {
            ...inventory.current,
            retired: retiredSources.current,
            serverAvailable: availability.get(turn.id),
          }),
        })),
      );
    } catch (error) {
      if (!aborted(error) && sequence === refreshSequence.current && alive.current)
        setLibraryError(errorText(error));
    } finally {
      requests.current.delete(controller);
      if (sequence === refreshSequence.current && alive.current) setLoading(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => {
      alive.current = false;
      requests.current.forEach((c) => c.abort());
      watchers.current.forEach((c) => c.abort());
    };
    // API is fixed for this build; mount performs one library load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (!turns.length || buddyOpen) return;
    if (followResults.current)
      resultsEnd.current?.scrollIntoView({ behavior: 'instant', block: 'nearest' });
    else setNewResults(true);
  }, [turns.length]);
  useEffect(() => {
    const track = () => {
      followResults.current = document.documentElement.scrollHeight - scrollY - innerHeight < 140;
    };
    window.addEventListener('scroll', track, { passive: true });
    return () => window.removeEventListener('scroll', track);
  }, []);

  async function watchImport(id: string) {
    if (watchers.current.has(id)) return;
    const controller = new AbortController();
    watchers.current.set(id, controller);
    setWatchErrors((previous) => ({ ...previous, [id]: '' }));
    try {
      const job = await pollJob(
        api,
        id,
        (update) => {
          setJobs((previous) => ({ ...previous, [id]: update }));
        },
        controller.signal,
      );
      if (alive.current) {
        setJobs((previous) => ({ ...previous, [id]: job }));
        await refresh();
      }
    } catch (error) {
      if (!aborted(error) && alive.current)
        setWatchErrors((previous) => ({ ...previous, [id]: errorText(error) }));
    } finally {
      watchers.current.delete(id);
    }
  }
  async function importUrls(event: FormEvent) {
    event.preventDefault();
    if (importing) return;
    const list = urls
      .split(/\r?\n/)
      .map((url) => url.trim())
      .filter(Boolean);
    if (!list.length) {
      setImportError('กรุณาวางลิงก์อย่างน้อย 1 รายการ');
      return;
    }
    if (list.length > 50) {
      setImportError('นำเข้าได้ครั้งละไม่เกิน 50 ลิงก์');
      return;
    }
    setImporting(true);
    setImportError('');
    const controller = newRequest();
    try {
      const response = await api.importVideos(list, controller.signal);
      setImports(
        response.jobs.map((item) => ({ url: list[item.input_index] || 'ไม่ทราบ URL', item })),
      );
      response.jobs
        .filter((item) => item.job_id && item.outcome !== 'rejected')
        .forEach((item) => void watchImport(item.job_id!));
      await refresh();
    } catch (error) {
      if (!aborted(error) && alive.current) setImportError(errorText(error));
    } finally {
      requests.current.delete(controller);
      if (alive.current) setImporting(false);
    }
  }
  async function completeTask(op: Operation, result: TaskResult, job?: Job, signal?: AbortSignal) {
    const artifacts = result.artifact_ids?.length ? [] : [...(result.artifacts || [])];
    for (const id of result.artifact_ids || []) artifacts.push(await api.artifact(id, signal));
    if (!alive.current) return;
    const sourcesAvailable = job?.sources_available ?? result.sources_available;
    const displayResult = ['quiz', 'flashcards', 'study_plan'].includes(op.type)
      ? { coverage: result.coverage }
      : result;
    updateTurns((previous) =>
      previous.some((turn) => turn.id === op.key)
        ? previous
        : [
            ...previous,
            {
              id: op.key,
              type: op.type,
              label: op.label,
              sources: op.sources,
              jobId: op.jobId || result.job_id || job?.job_id,
              result: reconcileSources(
                {
                  ...displayResult,
                  sources_available: sourcesAvailable,
                  artifacts: artifacts.map((artifact) => ({
                    ...artifact,
                    sources_available:
                      sourcesAvailable === false ? false : artifact.sources_available,
                  })),
                },
                op.sources,
                { ...inventory.current, retired: retiredSources.current },
              ),
              partial: job?.state === 'partial',
            },
          ],
    );
    if (op.type === 'chat' && result.conversation_id) {
      setConversation(result.conversation_id);
      conversationId.current = result.conversation_id;
      conversationScope.current = scopeFingerprint(
        (op.payload as { scope: import('./types').Scope }).scope,
      );
    }
    setOperation(null);
    operationRef.current = null;
    setCanRetry(false);
  }
  async function execute(op: Operation, resume = false) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setTaskError('');
    setCanRetry(false);
    setOperation(op);
    operationRef.current = op;
    const controller = newRequest();
    let currentOp = op;
    try {
      if (!resume) {
        const response = await api.submit(op.path, op.payload, op.key, controller.signal);
        if (response.status === 200) {
          await completeTask(op, response.data, undefined, controller.signal);
          return;
        }
        currentOp = { ...op, jobId: response.data.job_id };
        setOperation(currentOp);
        operationRef.current = currentOp;
      }
      if (!currentOp.jobId) throw new Error('ไม่พบรหัสงานสำหรับติดตามผล');
      let lastEvent = 0;
      const job = await pollJob(
        api,
        currentOp.jobId,
        async (update) => {
          setJobs((previous) => ({ ...previous, [update.job_id]: update }));
          if (currentOp.type === 'research') {
            const progress = await api.research(update.job_id, lastEvent, controller.signal);
            if (progress.events?.length) {
              lastEvent = Math.max(lastEvent, ...progress.events.map((e) => e.event_id));
              setEvents((previous) =>
                [...previous, ...progress.events].filter(
                  (e, i, all) => all.findIndex((x) => x.event_id === e.event_id) === i,
                ),
              );
            }
          }
        },
        controller.signal,
      );
      const warning = jobWarning(job);
      if (warning) {
        setTaskError(warning);
        setOperation(null);
        operationRef.current = null;
        return;
      }
      if (!job.result)
        throw new ApiError(
          'งานสิ้นสุดแล้วแต่ไม่มีผลลัพธ์ กรุณาตรวจสอบกับ backend',
          'missing_result',
          false,
        );
      await completeTask(currentOp, job.result, job, controller.signal);
    } catch (error) {
      if (!aborted(error) && alive.current) {
        if (error instanceof ApiError && error.jobId) {
          currentOp = { ...currentOp, jobId: error.jobId };
          setOperation(currentOp);
          operationRef.current = currentOp;
        }
        setTaskError(
          `${errorText(error)}${error instanceof ApiError && error.requestId ? ` · Request ID: ${error.requestId}` : ''}`,
        );
        setCanRetry(!!currentOp.jobId || !(error instanceof ApiError) || error.retryable);
        if (!currentOp.jobId && error instanceof ApiError && !error.retryable) {
          setOperation(null);
          operationRef.current = null;
        }
      }
    } finally {
      requests.current.delete(controller);
      busyRef.current = false;
      if (alive.current) setBusy(false);
    }
  }
  function submitTask(event: FormEvent, forcedType?: TaskType) {
    event.preventDefault();
    if (busyRef.current || operationRef.current) return;
    setTaskError('');
    try {
      if (libraryError || loading) throw new Error('กรุณาโหลดคลังคลิปให้สำเร็จก่อนส่งคำถาม');
      const scope = buildScope(selected, videos, channel, from, to);
      const type = forcedType || (tab === 'learn' ? taskType : 'chat');
      if (
        type === 'compare' &&
        scope.video_ids.filter((id) => {
          const v = videos.find((video) => video.video_id === id)!;
          return (
            (!channel || v.channel_id === channel) &&
            (!from || (!!v.published_at && v.published_at.slice(0, 10) >= from)) &&
            (!to || (!!v.published_at && v.published_at.slice(0, 10) <= to))
          );
        }).length < 2
      )
        throw new Error('เลือกคลิปที่ตรงตัวกรองอย่างน้อย 2 คลิปเพื่อเปรียบเทียบ');
      if ((type === 'chat' || type === 'research') && !question.trim())
        throw new Error(type === 'chat' ? 'กรุณาพิมพ์คำถาม' : 'กรุณาระบุเป้าหมายค้นคว้า');
      if (type !== 'chat' && (!Number.isInteger(days) || days < 1 || days > 90))
        throw new Error('จำนวนวันต้องเป็นเลขจำนวนเต็มตั้งแต่ 1–90');
      const text = question.trim();
      const sameScope = conversationScope.current === scopeFingerprint(scope);
      if (type === 'chat' && conversation && !sameScope)
        setScopeNotice('ชุดคลิปเปลี่ยนแล้ว คำถามนี้เริ่มบทสนทนาใหม่');
      else setScopeNotice('');
      const payload =
        type === 'chat'
          ? { question: text, conversation_id: sameScope ? conversation : null, scope }
          : type === 'summary' || type === 'compare'
            ? { type, scope, instruction: text }
            : type === 'research'
              ? { goal: text, scope, level, days }
              : { type, scope, topic: text, level, days };
      const path =
        type === 'chat'
          ? '/api/chat'
          : type === 'summary' || type === 'compare'
            ? '/api/analysis'
            : type === 'research'
              ? '/api/research'
              : '/api/learning-artifacts';
      setEvents([]);
      void execute({
        key: crypto.randomUUID(),
        path,
        payload,
        label: text || taskNames[type],
        type,
        sources: snapshotSources(videos, scope, libraryRevisions.current),
      });
    } catch (error) {
      setTaskError(errorText(error));
    }
  }
  function resetConversation() {
    if (busyRef.current || operationRef.current) return;
    setConversation(null);
    conversationId.current = null;
    conversationScope.current = '';
    setScopeNotice('');
    setQuestion('');
    updateTurns((previous) => previous.filter((turn) => turn.type !== 'chat'));
  }
  async function loadHistory() {
    if (!conversation || historyPending) return;
    const controller = newRequest();
    const expected = conversation;
    setHistoryPending(true);
    try {
      const messages: import('./types').ConversationPage['messages'] = [];
      let offset = 0;
      while (true) {
        const data = await api.history(expected, offset, controller.signal);
        messages.push(...data.messages);
        offset += data.messages.length;
        if (offset >= data.total) break;
        if (!data.messages.length) throw new Error('ประวัติยังโหลดไม่ครบ กรุณาลองใหม่');
      }
      if (!alive.current || expected !== conversationId.current) return;
      updateTurns((previous) => [
        ...previous,
        ...messages
          .filter(
            (message) =>
              message.role === 'assistant' &&
              !previous.some((turn) => turn.jobId === message.job_id),
          )
          .map((message) => {
            const sources = message.scope.map((source) => ({
              video_id: source.video_id,
              generation: source.generation,
              indexed_version: source.transcript_version,
              accessRevision: 0,
            }));
            return {
              id: `history-${message.message_id}`,
              type: 'chat' as const,
              label:
                messages.find((item) => item.job_id === message.job_id && item.role === 'user')
                  ?.content || 'คำถามก่อนหน้า',
              jobId: message.job_id,
              sources,
              partial: message.state === 'partial',
              result: reconcileSources(
                { answer: message.content, citations: message.citations },
                sources,
                { ...inventory.current, retired: retiredSources.current },
              ),
            };
          }),
      ]);
      setScopeNotice(`โหลดประวัติแล้ว ${messages.length} ข้อความ`);
    } catch (error) {
      if (!aborted(error) && alive.current) setTaskError(errorText(error));
    } finally {
      requests.current.delete(controller);
      if (alive.current) setHistoryPending(false);
    }
  }
  async function jobAction(id: string, action: 'cancel' | 'retry') {
    setActionError('');
    try {
      if (action === 'cancel') {
        const updated = await api.cancel(id);
        setJobs((previous) => ({ ...previous, [id]: updated }));
      } else {
        const accepted = await api.retry(id);
        setJobs((previous) => {
          const next = { ...previous };
          delete next[id];
          return next;
        });
        setWatchErrors((previous) => {
          const next = { ...previous };
          delete next[id];
          return next;
        });
        setImports((previous) =>
          previous.map((row) =>
            row.item.job_id === id
              ? { ...row, item: { ...row.item, job_id: accepted.job_id } }
              : row,
          ),
        );
        void watchImport(accepted.job_id);
      }
      await refresh();
    } catch (error) {
      setActionError(errorText(error));
    }
  }
  async function deleteVideo() {
    if (!deleteTarget) return;
    const id = deleteTarget;
    setDeleteTarget(null);
    setActionError('');
    try {
      const job = await api.deleteVideo(id);
      const affected = [
        ...inventory.current.videos,
        ...turnsRef.current.flatMap((turn) => turn.sources),
        ...(operationRef.current?.sources || []),
      ].filter((source) => source.video_id === id);
      affected.forEach((source) => retiredSources.current.add(sourceKey(source)));
      libraryRevisions.current.set(id, (libraryRevisions.current.get(id) || 0) + 1);
      inventory.current = {
        ...inventory.current,
        videos: inventory.current.videos.filter((video) => video.video_id !== id),
      };
      updateTurns((previous) =>
        previous.map((turn) => ({
          ...turn,
          result: reconcileSources(turn.result, turn.sources, {
            unavailableVideoIds: new Set([id]),
            retired: retiredSources.current,
          }),
        })),
      );
      setSelected((previous) => previous.filter((value) => value !== id));
      await refresh();
      void watchImport(job.job_id);
    } catch (error) {
      setActionError(errorText(error));
    }
  }

  const ready = videos.filter((v) => v.status === 'ready');
  const filtered = videos.filter(
    (v) =>
      (!channel || v.channel_id === channel) &&
      (!from || (!!v.published_at && v.published_at.slice(0, 10) >= from)) &&
      (!to || (!!v.published_at && v.published_at.slice(0, 10) <= to)),
  );
  const channels = [
    ...new Map(
      videos
        .filter((v) => v.channel_id)
        .map((v) => [v.channel_id!, v.channel_title || v.channel_id!]),
    ).entries(),
  ];
  const pendingJob = operation?.jobId ? jobs[operation.jobId] : null;
  const taskLocked = busy || !!operation;
  const synthetic = demo || mode === 'fixture';

  return (
    <div className={`app-shell forest-workspace view-${tab}`}>
      <ForestBackdrop />
      <a className="skip-link" href="#workspace">
        ข้ามไปเนื้อหา
      </a>
      <aside className="sidebar">
        <a className="brand" href="#workspace" aria-label="YouTube Knowledge หน้าหลัก">
          <span className="brand-mark">▶</span>
          <span>
            YouTube
            <strong>
              Knowledge<span className="brand-dot">.</span>
            </strong>
          </span>
        </a>
        <div className="sidebar-caption">พื้นที่ความรู้ของคุณ</div>
        <nav aria-label="เมนูหลัก">
          {(
            [
              ['library', 'คลังวิดีโอ', 'library'],
              ['chat', 'ถามจากคลิป', 'chat'],
              ['learn', 'วิเคราะห์และเรียนรู้', 'learn'],
            ] as const
          ).map(([id, label, icon]) => (
            <button
              key={id}
              className={tab === id ? 'nav-item active' : 'nav-item'}
              onClick={() => navigateTab(id)}
              aria-current={tab === id ? 'page' : undefined}
            >
              <Icon name={icon} />
              {label}
              {id === 'library' && <span>{total}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-tip">
          <img src="/rag-buddy.png" alt="RAG Buddy มาสคอตผู้ช่วยเรียนรู้" />
          <strong>ทุกคำตอบ มีที่มา</strong>
          <p>เลือกคลิปที่สนใจ แล้วเปลี่ยนสิ่งที่ดูให้เป็นความรู้ของคุณ</p>
        </div>
        <div className="sidebar-footer">
          <span className={`connection-dot ${synthetic ? 'demo' : ''}`} />
          {synthetic ? 'โหมดข้อมูลจำลอง' : mode === 'unknown' ? 'รอเชื่อมต่อ API' : 'เชื่อมต่อ API'}
          <small>YOUR VIDEO LEARNING SPACE</small>
        </div>
      </aside>
      <main id="workspace" className="workspace" tabIndex={-1}>
        <header className="topbar">
          <BuddyLogo onClick={() => navigateTab('home')} />
          <nav className="forest-nav" aria-label="เมนูพื้นที่เรียนรู้">
            {(
              [
                ['home', 'หน้าแรก'],
                ['library', 'คลังวิดีโอ'],
                ['chat', 'ถามจากคลิป'],
                ['learn', 'วิเคราะห์และเรียนรู้'],
              ] as const
            ).map(([view, label]) => (
              <button
                key={view}
                className={tab === view ? 'active' : ''}
                aria-current={tab === view ? 'page' : undefined}
                onClick={() => navigateTab(view)}
              >
                {label}
              </button>
            ))}
          </nav>
          <div className="profile-controls">
            {member && (
              <button
                ref={buddyRestore}
                className="secondary buddy-restore"
                onClick={() => {
                  setBuddyHidden(false);
                  setBuddyOpen(true);
                }}
              >
                เปิดแชต Buddy
              </button>
            )}
            {adminEnabled && (
              <button className="admin-link" onClick={() => onNavigate?.('/admin')}>
                จัดการระบบ
              </button>
            )}
            {member && (
              <div className="profile-pill">
                <span className="avatar" aria-hidden="true">
                  {member.name.slice(0, 1)}
                </span>
                <span>{member.name}</span>
                <span className="profile-separator" />
                <button onClick={onLogout}>ออกจากระบบ</button>
              </div>
            )}
          </div>
          <div className="breadcrumb">
            พื้นที่ทำงาน <span>/</span>{' '}
            <strong>
              {tab === 'library'
                ? 'คลังวิดีโอ'
                : tab === 'chat'
                  ? 'ถามจากคลิป'
                  : 'วิเคราะห์และเรียนรู้'}
            </strong>
          </div>
          <span className="private-badge">◉ พื้นที่ส่วนตัว · ต้นแบบผู้ใช้เดียว</span>
        </header>
        {synthetic && (
          <div className="demo-banner" role="status">
            <strong>DEMO · ข้อมูลจำลอง</strong>
            <span>
              เนื้อหาและคำตอบสังเคราะห์สำหรับทดลองหน้าเว็บ ไม่ได้ดึงเนื้อหาจริงหรือเรียก AI
            </span>
          </div>
        )}
        <div className="page-body">
          {tab === 'home' && (
            <HomeHero
              name={member?.name || 'ผู้เรียน'}
              value={urls}
              busy={importing}
              change={setUrls}
              submit={(event) => {
                navigateTab('library');
                void importUrls(event);
              }}
              openLibrary={() => navigateTab('library')}
              openChat={() => navigateTab('chat')}
            />
          )}
          {tab !== 'home' && (
            <div className="page-heading">
              <div>
                <span className="eyebrow">WATCH LESS. UNDERSTAND MORE.</span>
                <h1>
                  {tab === 'library'
                    ? 'คลังวิดีโอของคุณ'
                    : tab === 'chat'
                      ? 'ความรู้ เริ่มจากคำถาม'
                      : 'ต่อยอดทุกการเรียนรู้'}
                  <span className="heading-dot">.</span>
                </h1>
                <p>
                  {tab === 'library'
                    ? 'รวบรวมคลิปที่สนใจ แล้วค้นพบคำตอบจากสิ่งที่คุณเลือกดู'
                    : 'คำตอบและการเรียนรู้ที่เชื่อมกลับไปยังหลักฐานในคลิปที่คุณเลือก'}
                </p>
              </div>
              <span className="section-number" aria-hidden="true">
                {tab === 'library' ? '01' : tab === 'chat' ? '02' : '03'}
              </span>
            </div>
          )}
          {tab === 'library' && (
            <section className="import-panel" aria-labelledby="import-title">
              <div className="import-description">
                <span className="plus-tile">
                  <Icon name="plus" />
                </span>
                <h2 id="import-title">เพิ่มวิดีโอเข้าคลัง</h2>
                <p>
                  วางลิงก์ YouTube เพื่อเริ่มสร้างฐานความรู้
                  <br />
                  รองรับหลายลิงก์ แยกบรรทัดละ 1 ลิงก์
                </p>
                <span className="tiny-label">YOUTUBE → KNOWLEDGE</span>
              </div>
              <form onSubmit={importUrls} className="import-form">
                <label htmlFor="video-urls">ลิงก์วิดีโอ YouTube</label>
                <textarea
                  id="video-urls"
                  placeholder={'https://www.youtube.com/watch?v=...\nhttps://youtu.be/...'}
                  value={urls}
                  onChange={(e) => setUrls(e.target.value)}
                  rows={3}
                  disabled={importing}
                />
                <div className="form-footer">
                  <small>HTTPS · watch / youtu.be · สูงสุด 50 ลิงก์</small>
                  <button className="primary" disabled={importing || !urls.trim()}>
                    {importing ? 'กำลังส่ง…' : 'เพิ่มวิดีโอ'}
                    <Icon name="arrow" />
                  </button>
                </div>
                {importError && (
                  <p className="error" role="alert">
                    {importError}
                  </p>
                )}
              </form>
            </section>
          )}
          {tab === 'library' && imports.length > 0 && (
            <section className="import-results" aria-label="ผลนำเข้ารายลิงก์" aria-live="polite">
              {imports.map(({ url, item }, i) => {
                const job = item.job_id ? jobs[item.job_id] : null;
                return (
                  <div className="import-row" key={`${i}-${url}`}>
                    <span className={`outcome ${item.outcome}`}>
                      {item.outcome === 'accepted'
                        ? 'รับเข้าคิวแล้ว'
                        : item.outcome === 'existing'
                          ? 'มีอยู่แล้ว'
                          : 'ปฏิเสธ'}
                    </span>
                    <span className="import-url">{url}</span>
                    <span>
                      {job
                        ? statusLabels[job.stage] || statusLabels[job.state]
                        : item.error_code || ''}
                    </span>
                    {job?.state === 'failed' && job.retryable && (
                      <button
                        className="text-button"
                        onClick={() => void jobAction(job.job_id, 'retry')}
                      >
                        ลองนำเข้าใหม่
                      </button>
                    )}
                    {item.job_id && watchErrors[item.job_id] && (
                      <div className="error">
                        {watchErrors[item.job_id]}{' '}
                        <button onClick={() => void watchImport(item.job_id!)}>
                          ติดตามผลอีกครั้ง
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </section>
          )}
          <section className="library-section" aria-labelledby="library-title">
            <div className="section-heading">
              <div>
                <h2 id="library-title">
                  {tab === 'home'
                    ? 'คลังวิดีโอของคุณ'
                    : tab === 'library'
                      ? 'วิดีโอทั้งหมด'
                      : 'แหล่งข้อมูลสำหรับงานนี้'}{' '}
                  <span className="count">{total}</span>
                </h2>
                <p>
                  {ready.length} คลิปพร้อมใช้งานในรายการที่โหลด · เลือกไว้ {selected.length} คลิป
                </p>
              </div>
              <button className="secondary" onClick={() => void refresh()} disabled={loading}>
                {loading ? 'กำลังโหลด…' : '↻ รีเฟรชคลัง'}
              </button>
            </div>
            <div className="filters">
              <label>
                ช่อง
                <select value={channel} onChange={(e) => setChannel(e.target.value)}>
                  <option value="">ทุกช่อง</option>
                  {channels.map(([id, title]) => (
                    <option value={id} key={id}>
                      {title}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                ตั้งแต่วันที่
                <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
              </label>
              <label>
                ถึงวันที่
                <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
              </label>
              <button
                className="text-button"
                onClick={() => {
                  setChannel('');
                  setFrom('');
                  setTo('');
                }}
              >
                ล้างตัวกรอง
              </button>
              <span className="selection-caption">เลือกเฉพาะคลิปที่พร้อมใช้งาน</span>
            </div>
            {from && to && from > to && (
              <p className="error" role="alert">
                วันเริ่มต้นต้องไม่อยู่หลังวันสิ้นสุด
              </p>
            )}
            {libraryError && (
              <div className="notice error" role="alert">
                {libraryError}
                <button className="text-button" onClick={() => void refresh()}>
                  ลองโหลดอีกครั้ง
                </button>
              </div>
            )}
            {!loading && !libraryError && !filtered.length && (
              <div className="empty-state">
                <Icon name="library" />
                <h3>
                  {videos.length ? 'ไม่พบคลิปที่ตรงตัวกรอง' : 'เริ่มคลังความรู้คลิปแรกของคุณ'}
                </h3>
                <p>
                  {videos.length
                    ? 'ลองปรับช่องหรือช่วงวันที่'
                    : 'วางลิงก์ YouTube ด้านบน แล้วรอจนคลิปพร้อมใช้งาน'}
                </p>
              </div>
            )}
            <div className={`video-grid ${tab === 'chat' || tab === 'learn' ? 'compact' : ''}`}>
              {filtered.map((video, i) => (
                <article
                  className={`video-card ${selected.includes(video.video_id) ? 'selected' : ''}`}
                  key={video.video_id}
                >
                  <div className={`video-cover cover-${i % 4}`}>
                    <span className="cover-grain" />
                    <Thumbnail url={video.thumbnail_url} />
                    <span className="cover-topic">
                      {synthetic ? 'DEMO LESSON' : 'VIDEO KNOWLEDGE'}
                    </span>
                    <span className="cover-title">{video.title || video.video_id}</span>
                    <a
                      className="play-button"
                      href={
                        videoIdFromUrl(video.canonical_url)
                          ? `https://www.youtube.com/watch?v=${video.video_id}`
                          : undefined
                      }
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`เปิดวิดีโอ ${video.title || video.video_id}`}
                    >
                      ▶
                    </a>
                    <span className={`status-pill ${video.status}`}>
                      {statusLabels[video.status] || video.status}
                    </span>
                  </div>
                  <div className="video-info">
                    <div className="video-title-row">
                      <label className="video-select">
                        <input
                          type="checkbox"
                          aria-label={`เลือก ${video.title || video.video_id}`}
                          checked={selected.includes(video.video_id)}
                          disabled={video.status !== 'ready'}
                          onChange={(e) =>
                            setSelected((previous) =>
                              e.target.checked
                                ? [...previous, video.video_id]
                                : previous.filter((id) => id !== video.video_id),
                            )
                          }
                        />
                        <strong>{video.title || video.video_id}</strong>
                      </label>
                      <button
                        className="delete-button"
                        aria-label={`ลบ ${video.title || video.video_id}`}
                        onClick={() => setDeleteTarget(video.video_id)}
                      >
                        ×
                      </button>
                    </div>
                    <p>{video.channel_title || 'ยังไม่มีข้อมูลช่อง'}</p>
                    <small>
                      {video.published_at
                        ? video.published_at.slice(0, 10)
                        : 'ยังไม่มีวันที่เผยแพร่'}
                    </small>
                  </div>
                </article>
              ))}
            </div>
            {videos.length < total && (
              <button
                className="secondary load-more"
                disabled={loading}
                onClick={() => void refresh(pageCount.current + 1)}
              >
                โหลดคลิปเพิ่มเติม ({videos.length}/{total})
              </button>
            )}
            {selected.length > 0 && tab === 'library' && (
              <div className="selection-bar">
                <div>
                  <strong>เลือกไว้ {selected.length} คลิป</strong>
                  <span>พร้อมเป็นแหล่งข้อมูลของคุณ</span>
                </div>
                <button className="primary" onClick={() => navigateTab('chat')}>
                  ถามจากคลิปที่เลือก
                  <Icon name="arrow" />
                </button>
              </div>
            )}
          </section>
          {(tab === 'chat' || tab === 'learn') && (
            <section className="chat-panel" aria-labelledby="task-title">
              <div className="section-heading">
                <div>
                  <span className="eyebrow">GROUNDED IN YOUR VIDEOS</span>
                  <h2 id="task-title">
                    {tab === 'chat' ? 'ถามสิ่งที่อยากรู้' : 'เลือกวิธีเรียนรู้'}
                  </h2>
                </div>
                {tab === 'chat' && (
                  <button className="text-button" disabled={taskLocked} onClick={resetConversation}>
                    เริ่มบทสนทนาใหม่
                  </button>
                )}
              </div>
              <form onSubmit={submitTask}>
                {tab === 'learn' && (
                  <div className="learning-controls">
                    <label>
                      ประเภทงาน
                      <select
                        value={taskType}
                        disabled={taskLocked}
                        onChange={(e) => setTaskType(e.target.value as TaskType)}
                      >
                        {Object.entries(taskNames)
                          .filter(([key]) => key !== 'chat')
                          .map(([key, name]) => (
                            <option key={key} value={key}>
                              {name}
                            </option>
                          ))}
                      </select>
                    </label>
                    {['research', 'quiz', 'flashcards', 'study_plan'].includes(taskType) && (
                      <>
                        <label>
                          ระดับ
                          <select
                            value={level}
                            disabled={taskLocked}
                            onChange={(e) => setLevel(e.target.value)}
                          >
                            <option value="beginner">เริ่มต้น</option>
                            <option value="intermediate">ปานกลาง</option>
                            <option value="advanced">ขั้นสูง</option>
                          </select>
                        </label>
                        {['research', 'study_plan'].includes(taskType) && (
                          <label>
                            จำนวนวัน
                            <input
                              type="number"
                              min="1"
                              max="90"
                              value={days}
                              disabled={taskLocked}
                              onChange={(e) => setDays(Number(e.target.value))}
                            />
                          </label>
                        )}
                      </>
                    )}
                  </div>
                )}
                <label htmlFor="question">
                  {tab === 'chat'
                    ? 'คำถามของคุณ'
                    : taskType === 'research'
                      ? 'เป้าหมายค้นคว้า'
                      : 'หัวข้อหรือคำแนะนำเพิ่มเติม'}
                </label>
                <textarea
                  id="question"
                  value={question}
                  disabled={taskLocked}
                  onChange={(e) => setQuestion(e.target.value)}
                  maxLength={tab === 'chat' || taskType === 'research' ? 12000 : 4000}
                  rows={3}
                  placeholder={
                    tab === 'chat'
                      ? 'คลิปเหล่านี้อธิบายเรื่อง RAG ไว้อย่างไร?'
                      : 'อยากเรียนรู้หรือเจาะลึกเรื่องอะไร…'
                  }
                />
                <div className="form-footer">
                  <small>อ้างอิงเฉพาะคลิปที่เลือกและตรงกับตัวกรอง</small>
                  <button
                    className="primary"
                    disabled={taskLocked || !selected.length || loading || !!libraryError}
                  >
                    {busy ? 'กำลังทำงาน…' : tab === 'chat' ? 'ส่งคำถาม' : 'เริ่มงาน'}
                    <Icon name="arrow" />
                  </button>
                </div>
              </form>
              {operation && (
                <div className="pending-panel" role="status">
                  <strong>{busy ? 'กำลังติดตามงาน' : 'คำขอนี้ยังรอการตรวจสอบผล'}</strong>
                  <span>{operation.label}</span>
                  {pendingJob && (
                    <span>
                      {statusLabels[pendingJob.state]} · {pendingJob.stage} · ครั้งที่{' '}
                      {pendingJob.attempt_count}/{pendingJob.max_attempts}
                    </span>
                  )}
                  {operation.jobId && <small>Job ID: {operation.jobId}</small>}
                  {operation.jobId && !terminal(pendingJob?.state || '') && (
                    <button
                      className="secondary"
                      onClick={() => void jobAction(operation.jobId!, 'cancel')}
                    >
                      ขอยกเลิกงาน
                    </button>
                  )}
                </div>
              )}
              {taskError && (
                <div className="notice error" role="alert">
                  {taskError}
                </div>
              )}
              {!busy && operation && canRetry && (
                <button
                  className="secondary"
                  onClick={() => void execute(operation, !!operation.jobId)}
                >
                  {operation.jobId ? 'ติดตามผลอีกครั้ง' : 'ส่งคำขอเดิมซ้ำ'}
                </button>
              )}
              {events.length > 0 && (
                <details className="progress-events" open>
                  <summary>ความคืบหน้าการค้นคว้า</summary>
                  {events.map((event) => (
                    <p key={event.event_id}>
                      <strong>
                        ขั้นที่ {event.step} · {event.tool_name}
                      </strong>{' '}
                      {event.summary}
                    </p>
                  ))}
                </details>
              )}
              {newResults && (
                <button
                  className="text-button"
                  onClick={() => {
                    resultsEnd.current?.scrollIntoView({ behavior: 'instant', block: 'nearest' });
                    followResults.current = true;
                    setNewResults(false);
                  }}
                >
                  มีผลลัพธ์ใหม่ ↓
                </button>
              )}
              {tab === 'chat' && conversation && (
                <button
                  className="text-button"
                  disabled={historyPending}
                  onClick={() => void loadHistory()}
                >
                  โหลดประวัติบทสนทนานี้
                </button>
              )}
              <div
                className="turns"
                ref={resultsViewport}
                onWheel={(event) => {
                  if (event.deltaY < 0) followResults.current = false;
                }}
                onTouchMove={() => {
                  followResults.current = false;
                }}
              >
                {turns.map((turn) => (
                  <article className="turn" key={turn.id}>
                    <div className="user-question">{turn.label}</div>
                    <div className="assistant-label">
                      <span className="assistant-mark">✦</span> Knowledge Assistant
                    </div>
                    <ResultView result={turn.result} partial={turn.partial} />
                  </article>
                ))}
                <div ref={resultsEnd} />
              </div>
            </section>
          )}
          {sourceCheckError && (
            <p className="notice warning" role="status">
              {sourceCheckError}
            </p>
          )}
          {actionError && (
            <p className="notice error" role="alert">
              {actionError}
            </p>
          )}
          {Object.values(jobs)
            .filter((job) => job.kind === 'delete' || job.kind === 'detach')
            .map((job) => (
              <div className="notice" key={job.job_id}>
                {job.kind === 'detach' ? 'นำออกจากคลัง' : 'การลบคลิป'}: {statusLabels[job.state]}
                {job.error_code && ` · ${job.error_code}`}
                {job.state === 'failed' && job.retryable && (
                  <button onClick={() => void jobAction(job.job_id, 'retry')}>ลองลบใหม่</button>
                )}
                {watchErrors[job.job_id] && (
                  <>
                    <span>{watchErrors[job.job_id]}</span>
                    <button onClick={() => void watchImport(job.job_id)}>
                      ติดตามการลบอีกครั้ง
                    </button>
                  </>
                )}
              </div>
            ))}
          {tab === 'home' && (
            <section className="home-actions" aria-label="ทางลัดเรียนรู้">
              <div>
                <h2>ลองทำสิ่งนี้ดู</h2>
                <p>ต่อยอดจากคลิปที่คุณเลือก</p>
              </div>
              <button
                onClick={() => {
                  setTaskType('summary');
                  navigateTab('learn');
                }}
              >
                สรุปประเด็นสำคัญ ↗
              </button>
              <button onClick={() => navigateTab('chat')}>ถามจากคลิป ↗</button>
              <button
                onClick={() => {
                  setTaskType('quiz');
                  navigateTab('learn');
                }}
              >
                สร้างแบบทดสอบ ↗
              </button>
            </section>
          )}
          <footer className="page-footer">
            <span>YouTube Knowledge</span>
            <p>คำตอบที่ดี เริ่มต้นจากหลักฐานที่ตรวจสอบได้</p>
            <span>01 / WEB WORKSPACE</span>
          </footer>
        </div>
      </main>
      {member && (
        <FloatingBuddy
          open={buddyOpen}
          hidden={buddyHidden}
          onOpen={setBuddyOpen}
          onHide={setBuddyHidden}
          restoreRef={buddyRestore}
          videos={filtered}
          selected={selected}
          select={(id) =>
            setSelected((previous) =>
              previous.includes(id) ? previous.filter((value) => value !== id) : [...previous, id],
            )
          }
          question={question}
          change={setQuestion}
          submit={(event) => submitTask(event, 'chat')}
          turns={turns.filter((turn) => turn.type === 'chat')}
          locked={taskLocked || loading || !!libraryError}
          busy={busy}
          status={
            operation
              ? `${busy ? 'กำลังทำงาน' : 'รอตรวจสอบผล'}${pendingJob ? ` · ${statusLabels[pendingJob.state]} · ${pendingJob.stage}` : ''}`
              : ''
          }
          error={taskError || libraryError}
          scopeNotice={scopeNotice}
          newConversation={resetConversation}
          cancel={
            operation?.jobId && !terminal(pendingJob?.state || '')
              ? () => void jobAction(operation.jobId!, 'cancel')
              : undefined
          }
          retry={
            !busy && operation && canRetry
              ? () => void execute(operation, !!operation.jobId)
              : undefined
          }
          fullChat={() => navigateTab('chat')}
          history={() => void loadHistory()}
          historyAvailable={!!conversation}
          historyPending={historyPending}
        />
      )}
      {deleteTarget && (
        <DeleteDialog cancel={() => setDeleteTarget(null)} confirm={() => void deleteVideo()} />
      )}
    </div>
  );
}

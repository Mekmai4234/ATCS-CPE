import { useEffect, useMemo, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { Api, ApiError, pollJob } from './api';
import {
  buildScope,
  jobWarning,
  jobShouldPark,
  statusLabels,
  terminal,
  videoIdFromUrl,
  videoQueryable,
  jobStatus,
} from './domain';
import { EvidenceContext, SourceBadges } from './Evidence';
import { demoTransport } from './demo';
import { ResultView } from './Results';
import { reconcileSources, snapshotSources, sourceKey } from './sources';
import type { SourceSnapshot } from './types';
import type { ImportItem, Job, ProgressEvent, TaskResult, TaskType, Video } from './types';
import type { Member } from './session';
import { BuddyLogo, ForestBackdrop } from './Forest';
import HomeHero from './HomeHero';
import FloatingBuddy from './FloatingBuddy';
import InteractiveBuddy from './InteractiveBuddy';
import { scopeFingerprint } from './buddyModel';
import { UiIcon } from './Visuals';
import { importMessage, serviceMessage, userMessages } from './userMessages';
import ChatHistory from './ChatHistory';
import { BuddyArt } from './BuddyArt';
import JobRecovery from './JobRecovery';
import MediaEvidence from './MediaEvidence';

type WorkspaceView = 'home' | 'library' | 'chat' | 'learn' | 'history';
interface WorkspaceProps {
  api?: Api;
  member?: Member;
  initialView?: WorkspaceView;
  initialConversationId?: string;
  onNavigate?: (path: string) => void;
  onLogout?: () => void;
  adminEnabled?: boolean;
}

const demo = import.meta.env.VITE_DEMO_MODE === 'true';
const taskNames: Record<TaskType, string> = {
  chat: 'แชตกับ Buddy',
  summary: 'สรุปเนื้อหา',
  compare: 'เปรียบเทียบคลิป',
  research: 'ค้นคว้าหลายขั้นตอน',
  quiz: 'แบบทดสอบ',
  flashcards: 'แฟลชการ์ด',
  study_plan: 'แผนเรียน',
};
const workspaceMenu = [
  ['home', 'หน้าแรก', 'home'],
  ['library', 'วิดีโอของฉัน', 'library'],
  ['learn', 'สรุปและแบบฝึกหัด', 'learn'],
  ['history', 'ประวัติแชท', 'clock'],
] as const;
const learningTools = [
  ['summary', 'สรุป', 'library'],
  ['compare', 'เทียบ', 'learn'],
  ['research', 'ค้นคว้า', 'spark'],
  ['quiz', 'ทดสอบ', 'quiz'],
  ['flashcards', 'ทบทวน', 'library'],
  ['study_plan', 'วางแผน', 'clock'],
] as const;
interface Operation {
  detached?: boolean;
  key: string;
  path: string;
  payload: object;
  label: string;
  type: TaskType;
  jobId?: string;
  sources: SourceSnapshot[];
}
interface Turn {
  unanswered?: string;
  type?: TaskType;
  id: string;
  label: string;
  result: TaskResult;
  partial: boolean;
  jobId?: string;
  sources: SourceSnapshot[];
}
const errorText = (error: unknown) => {
  if (error instanceof ApiError) {
    const message = serviceMessage(error.code, error.status);
    if (message) return message;
  }
  return error instanceof Error ? error.message : userMessages.failed;
};
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
  initialConversationId,
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
    if (view !== 'learn') setLearningFocus(false);
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
  const [learningFocus, setLearningFocus] = useState(false);
  const [days, setDays] = useState(7);
  const [level, setLevel] = useState('beginner');
  const [conversation, setConversation] = useState<string | null>(null);
  const conversationId = useRef<string | null>(null);
  const conversationScope = useRef('');
  const [scopeNotice, setScopeNotice] = useState('');
  const [historyPending, setHistoryPending] = useState(false);
  const [buddyOpen, setBuddyOpen] = useState(false);
  const [sourcesExpanded, setSourcesExpanded] = useState(false);
  const [viewingHistory, setViewingHistory] = useState(false);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [archiveError, setArchiveError] = useState('');
  const [archiveAttempt, setArchiveAttempt] = useState(0);
  const loadedArchive = useRef<string | null>(null);
  const archiveSequence = useRef(0);
  const responseAnchor = useRef<HTMLDivElement>(null);
  const latestAnswer = useRef<HTMLElement>(null);
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
  const [deferred, setDeferred] = useState<Operation[]>([]);
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
        ids.filter((id) => all.some((v) => v.video_id === id && videoQueryable(v))),
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
    if (!turns.length || buddyOpen || viewingHistory || archiveLoading) return;
    if (followResults.current)
      latestAnswer.current?.scrollIntoView({ behavior: 'instant', block: 'start' });
    else setNewResults(true);
  }, [turns.length]);
  useEffect(() => {
    const track = (event: WheelEvent) => {
      if (event.deltaY < 0) followResults.current = false;
    };
    const touch = () => {
      followResults.current = false;
    };
    const key = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (
        !target.closest('input, textarea, select, [contenteditable="true"]') &&
        (['PageUp', 'Home', 'ArrowUp'].includes(event.key) || (event.key === ' ' && event.shiftKey))
      )
        followResults.current = false;
    };
    window.addEventListener('wheel', track, { passive: true });
    window.addEventListener('touchmove', touch, { passive: true });
    window.addEventListener('keydown', key);
    return () => {
      window.removeEventListener('wheel', track);
      window.removeEventListener('touchmove', touch);
      window.removeEventListener('keydown', key);
    };
  }, []);
  useEffect(() => {
    if (busy && !buddyOpen)
      responseAnchor.current?.scrollIntoView({ behavior: 'instant', block: 'start' });
  }, [busy, buddyOpen]);

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
    if (op.type === 'chat' && result.conversation_id && !op.detached) {
      setConversation(result.conversation_id);
      conversationId.current = result.conversation_id;
      conversationScope.current = scopeFingerprint(
        (op.payload as { scope: import('./types').Scope }).scope,
      );
    }
    setOperation(null);
    operationRef.current = null;
    setCanRetry(false);
    if (op.type !== 'chat') setLearningFocus(true);
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
          if (jobShouldPark(update))
            throw new ApiError(jobStatus(update), 'provider_wait', false, undefined, update.job_id);
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
      if (!job.result) throw new ApiError(userMessages.failed, 'missing_result', false);
      await completeTask(currentOp, job.result, job, controller.signal);
    } catch (error) {
      if (!aborted(error) && alive.current) {
        if (error instanceof ApiError && error.code === 'provider_wait' && currentOp.jobId) {
          setDeferred((previous) => [
            ...previous.filter((item) => item.jobId !== currentOp.jobId),
            { ...currentOp, detached: true },
          ]);
          setOperation(null);
          operationRef.current = null;
          setCanRetry(false);
          setTaskError('คำขอนี้ยังไม่เสร็จ คุณสามารถติดตามสถานะจากรายการงานที่พักไว้');
          return;
        }
        if (error instanceof ApiError && error.jobId) {
          currentOp = { ...currentOp, jobId: error.jobId };
          setOperation(currentOp);
          operationRef.current = currentOp;
        }
        setTaskError(errorText(error));
        if (currentOp.jobId) {
          try {
            const saved = await api.job(currentOp.jobId, controller.signal);
            if (!alive.current) return;
            setJobs((previous) => ({ ...previous, [saved.job_id]: saved }));
            if (terminal(saved.state)) {
              if ((saved.state === 'completed' || saved.state === 'partial') && saved.result) {
                setTaskError('');
                await completeTask(currentOp, saved.result, saved, controller.signal);
              } else {
                setTaskError(jobWarning(saved) || errorText(error));
                setOperation(null);
                operationRef.current = null;
                setCanRetry(false);
              }
              return;
            }
          } catch {
            // A failed status read leaves the durable job unresolved. Keep the
            // explicit follow-up action; never resubmit an ambiguous POST.
          }
        }
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
    if (archiveLoading || ((forcedType === 'chat' || tab === 'chat') && viewingHistory)) return;
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
      if (
        ['research', 'study_plan'].includes(type) &&
        (!Number.isInteger(days) || days < 1 || days > 90)
      )
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
              : { type, scope, topic: text, level, ...(type === 'study_plan' ? { days } : {}) };
      const path =
        type === 'chat'
          ? '/api/chat'
          : type === 'summary' || type === 'compare'
            ? '/api/analysis'
            : type === 'research'
              ? '/api/research'
              : '/api/learning-artifacts';
      setEvents([]);
      followResults.current = true;
      setNewResults(false);
      setSourcesExpanded(false);
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
    setTaskError('');
    setCanRetry(false);
    setNewResults(false);
    setViewingHistory(false);
    archiveSequence.current++;
    setArchiveLoading(false);
    setArchiveError('');
    loadedArchive.current = null;
    onNavigate?.('/chat');
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
  useEffect(() => {
    const sequence = ++archiveSequence.current;
    if (!initialConversationId) {
      loadedArchive.current = null;
      setArchiveLoading(false);
      setViewingHistory(false);
      setArchiveError('');
      return;
    }
    if (loadedArchive.current === initialConversationId) return;
    if (busyRef.current || operationRef.current) {
      setArchiveError('รอให้งานปัจจุบันสิ้นสุดก่อนเปิดบทสนทนาอื่น');
      return;
    }
    const controller = newRequest();
    setArchiveLoading(true);
    setArchiveError('');
    setViewingHistory(true);
    setTaskError('');
    updateTurns((previous) => previous.filter((turn) => turn.type !== 'chat'));
    setConversation(null);
    conversationId.current = null;
    followResults.current = false;
    void (async () => {
      const messages: import('./types').ConversationPage['messages'] = [];
      let scope: import('./types').Scope | null | undefined;
      let offset = 0;
      while (true) {
        const data = await api.history(initialConversationId, offset, controller.signal);
        scope = data.scope;
        messages.push(...data.messages);
        offset += data.messages.length;
        if (offset >= data.total) break;
        if (!data.messages.length) throw new Error('โหลดประวัติไม่ครบ กรุณาลองเปิดอีกครั้ง');
      }
      if (controller.signal.aborted || !alive.current || sequence !== archiveSequence.current)
        return;
      const restored: Turn[] = messages
        .filter((m) => m.role === 'user')
        .map((message) => {
          const reply = messages.find((m) => m.job_id === message.job_id && m.role === 'assistant');
          const sources = message.scope.map((s) => ({
            video_id: s.video_id,
            generation: s.generation,
            indexed_version: s.transcript_version,
            accessRevision: 0,
          }));
          return {
            id: `history-${message.message_id}`,
            type: 'chat',
            jobId: message.job_id,
            label: message.content,
            sources,
            partial: message.state === 'partial',
            unanswered: reply
              ? undefined
              : statusLabels[message.state] || 'ยังไม่มีคำตอบที่บันทึกไว้',
            result: reconcileSources(
              { answer: reply?.content, citations: reply?.citations || [] },
              sources,
              { ...inventory.current, retired: retiredSources.current },
            ),
          };
        });
      updateTurns((previous) => [...previous.filter((t) => t.type !== 'chat'), ...restored]);
      const savedScope = scope || {
        video_ids: [...new Set(messages.at(-1)?.scope.map((s) => s.video_id) || [])],
        channel_ids: [],
        date_from: null,
        date_to: null,
      };
      setSelected(savedScope.video_ids);
      setChannel(savedScope.channel_ids[0] || '');
      setFrom(savedScope.date_from || '');
      setTo(savedScope.date_to || '');
      setConversation(initialConversationId);
      conversationId.current = initialConversationId;
      conversationScope.current = scopeFingerprint(savedScope);
      setQuestion('');
      setNewResults(false);
      setScopeNotice('');
      setSourcesExpanded(false);
      loadedArchive.current = initialConversationId;
    })()
      .catch((error) => {
        if (!controller.signal.aborted && alive.current && sequence === archiveSequence.current)
          setArchiveError(
            error instanceof ApiError && error.status === 404
              ? 'ไม่พบบทสนทนานี้ หรือบัญชีของคุณไม่มีสิทธิ์เปิด'
              : errorText(error),
          );
      })
      .finally(() => {
        requests.current.delete(controller);
        if (!controller.signal.aborted && alive.current && sequence === archiveSequence.current)
          setArchiveLoading(false);
      });
    return () => {
      controller.abort();
    };
  }, [initialConversationId, busy, operation, archiveAttempt]);

  async function jobAction(id: string, action: 'cancel' | 'retry') {
    setActionError('');
    try {
      if (action === 'cancel') {
        const updated = await api.cancel(id);
        if (!alive.current) return;
        setJobs((previous) => ({ ...previous, [id]: updated }));
        // A stopped poller cannot observe cancellation on its next tick.
        // Release the composer only after the server confirms a terminal state.
        if (['cancelled', 'failed'].includes(updated.state)) {
          setDeferred((previous) => previous.filter((item) => item.jobId !== id));
          if (!busyRef.current && operationRef.current?.jobId === id) {
            setOperation(null);
            operationRef.current = null;
            setCanRetry(false);
            setTaskError(jobWarning(updated) || 'งานสิ้นสุดแล้ว');
          }
        }
      } else {
        if (!jobs[id] || !['import', 'delete'].includes(jobs[id].kind))
          throw new Error('API ยังไม่อนุญาตให้ retry งานชนิดนี้');
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
      setActionError(`ลบไม่สำเร็จ: ${errorText(error)}`);
    }
  }

  const ready = videos.filter(videoQueryable);
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
  const hasFilters = !!(channel || from || to);
  const selectedInFilter = filtered.filter(
    (video) => selected.includes(video.video_id) && videoQueryable(video),
  );
  const scopeHelp = loading
    ? 'กำลังโหลดวิดีโอของฉัน กรุณารอสักครู่'
    : libraryError
      ? 'โหลดวิดีโอของฉันไม่สำเร็จ กรุณาลองโหลดอีกครั้ง'
      : from && to && from > to
        ? 'วันเริ่มต้นต้องไม่อยู่หลังวันสิ้นสุด'
        : !selected.length
          ? 'เลือกคลิปอย่างน้อย 1 คลิปก่อนส่งคำถาม'
          : !selectedInFilter.length
            ? 'คลิปที่เลือกไม่ตรงตัวกรอง กรุณาล้างตัวกรองหรือเลือกคลิปใหม่'
            : selected.length > 100
              ? 'เลือกแหล่งข้อมูลได้สูงสุด 100 คลิป'
              : '';

  return (
    <EvidenceContext.Provider value={api.loadFrame}>
      <div
        className={`app-shell forest-workspace v5-workspace view-${tab}${tab === 'learn' && learningFocus ? ' learning-result' : ''}`}
      >
        <ForestBackdrop />
        <a className="skip-link" href="#workspace">
          ข้ามไปเนื้อหา
        </a>
        <aside className="sidebar v5-sidebar">
          <BuddyLogo onClick={() => navigateTab('home')} />
          <nav aria-label="เมนูหลัก">
            {workspaceMenu.map(([id, label, icon]) => (
              <button
                key={id}
                className={
                  tab === id || (id === 'history' && tab === 'chat')
                    ? 'nav-item active'
                    : 'nav-item'
                }
                aria-current={
                  tab === id || (id === 'history' && tab === 'chat') ? 'page' : undefined
                }
                onClick={() => navigateTab(id)}
              >
                <UiIcon name={icon} />
                <span>{label}</span>
              </button>
            ))}
          </nav>
          <div className="v5-sidebar-bottom">
            <a href="/help">
              <UiIcon name="help" />
              ช่วยเหลือ
            </a>
            {adminEnabled && (
              <button onClick={() => onNavigate?.('/admin')}>
                <UiIcon name="learn" />
                จัดการระบบ
              </button>
            )}
            {member && (
              <div className="v5-account">
                <span className="avatar" aria-hidden="true">
                  {member.name.slice(0, 1)}
                </span>
                <strong>{member.name}</strong>
                <button onClick={onLogout} aria-label="ออกจากระบบ">
                  <svg
                    width="22"
                    height="22"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    aria-hidden="true"
                  >
                    <path d="M9 4H4v16h5M9 12h11m-4-4 4 4-4 4" />
                  </svg>
                </button>
              </div>
            )}
          </div>
        </aside>
        <main id="workspace" className="workspace" tabIndex={-1}>
          <header className="topbar v5-topbar">
            <BuddyLogo onClick={() => navigateTab('home')} />
            <div className="v5-top-actions">
              <button
                aria-label="เปิดแชทกับ Buddy"
                onClick={() => (member ? setBuddyOpen(true) : navigateTab('chat'))}
              >
                <UiIcon name="chat" />
              </button>
              <a href="/help" aria-label="ช่วยเหลือ">
                <UiIcon name="help" />
              </a>
              {member && (
                <details className="v5-account-menu">
                  <summary aria-label="บัญชีผู้ใช้">
                    <span className="avatar" aria-hidden="true">
                      {member.name.slice(0, 1)}
                    </span>
                  </summary>
                  <div>
                    <strong>{member.name}</strong>
                    {adminEnabled && (
                      <button onClick={() => onNavigate?.('/admin')}>จัดการระบบ</button>
                    )}
                    <button onClick={onLogout}>ออกจากระบบ</button>
                  </div>
                </details>
              )}
            </div>
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
            {member && !demo && (
              <JobRecovery
                api={api}
                hasPending={
                  !!operation ||
                  deferred.length > 0 ||
                  Object.values(jobs).some((job) => !terminal(job.state))
                }
                locked={taskLocked || archiveLoading}
                restore={(job) => {
                  if (job.kind === 'import' || job.kind === 'enrich') {
                    void watchImport(job.job_id);
                    return;
                  }
                  const type: TaskType =
                    job.kind === 'chat'
                      ? 'chat'
                      : job.kind === 'research'
                        ? 'research'
                        : job.request.type || 'summary';
                  setTaskType(type === 'chat' ? 'summary' : type);
                  navigateTab(type === 'chat' ? 'chat' : 'learn');
                  void execute(
                    {
                      key: `recovered-${job.job_id}`,
                      jobId: job.job_id,
                      type,
                      path: '',
                      payload: job.request,
                      label:
                        job.request.question ||
                        job.request.goal ||
                        job.request.topic ||
                        job.request.instruction ||
                        taskNames[type],
                      sources: job.sources.map((source) => ({
                        video_id: source.video_id,
                        generation: source.generation,
                        indexed_version: source.transcript_version,
                        accessRevision: 0,
                      })),
                    },
                    true,
                  );
                }}
              />
            )}
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
            {tab === 'library' && (
              <section className="v5-library-stage" aria-labelledby="library-page-title">
                <div className="v5-library-copy">
                  <h1 id="library-page-title">
                    คลังคลิป<span className="v5-dot">.</span>
                  </h1>
                  <form onSubmit={importUrls} className="v5-url-form v5-library-form">
                    <label htmlFor="video-urls">ลิงก์วิดีโอ YouTube</label>
                    <div>
                      <textarea
                        id="video-urls"
                        placeholder="วางลิงก์คลิปที่นี่"
                        value={urls}
                        onChange={(e) => setUrls(e.target.value)}
                        rows={1}
                        disabled={importing}
                      />
                      <button
                        className="primary"
                        aria-label="เพิ่มคลิป (เพิ่มวิดีโอ)"
                        disabled={importing || !urls.trim()}
                      >
                        {importing ? 'กำลังเพิ่ม…' : 'เพิ่มคลิป'}
                        <Icon name="plus" />
                      </button>
                    </div>
                    <details className="v5-import-hint">
                      <summary>เพิ่มหลายคลิป</summary>
                      <p>แยกบรรทัดละ 1 ลิงก์ · สูงสุด 50 ลิงก์</p>
                    </details>
                    {importError && (
                      <p className="error" role="alert">
                        {importError}
                      </p>
                    )}
                  </form>
                </div>
                <div className="v5-library-art">
                  <span aria-hidden="true" />
                  <BuddyArt pose={videos.length ? 'library' : 'empty-library'} />
                </div>
              </section>
            )}
            {tab === 'learn' && !learningFocus && (
              <section className="v5-learning-stage" aria-labelledby="learning-title">
                <div className="v5-learning-copy">
                  <h1 id="learning-title">
                    เรียนรู้<span className="v5-dot">.</span>
                  </h1>
                  <div className="v5-source-select">
                    <UiIcon name="library" />
                    <span>
                      จาก <b>{selectedInFilter.length} คลิป</b>
                    </span>
                    <button
                      onClick={() => setSourcesExpanded((value) => !value)}
                      aria-expanded={sourcesExpanded}
                      aria-controls="chat-sources"
                    >
                      {sourcesExpanded ? 'ย่อคลิป' : 'เปลี่ยน'}
                      <UiIcon name="arrow" size={16} />
                    </button>
                  </div>
                  <div className="v5-tool-grid">
                    {learningTools.map(([id, label, icon]) => (
                      <button
                        key={id}
                        type="button"
                        className={'v5-tool v5-tool-' + id + (taskType === id ? ' active' : '')}
                        aria-pressed={taskType === id}
                        aria-label={
                          id === 'flashcards'
                            ? 'ทบทวนด้วยแฟลชการ์ด'
                            : id === 'study_plan'
                              ? 'วางแผนเรียน'
                              : taskNames[id]
                        }
                        disabled={taskLocked}
                        onClick={() => setTaskType(id)}
                      >
                        <UiIcon name={icon} />
                        <span>{label}</span>
                        <UiIcon name="arrow" size={18} />
                      </button>
                    ))}
                  </div>
                </div>
                <div className="v5-learning-art">
                  <span aria-hidden="true" />
                  <BuddyArt pose="learning" />
                </div>
              </section>
            )}
            {tab === 'learn' && learningFocus && (
              <>
                <h1 className="visually-hidden">{taskNames[taskType]}</h1>
                <nav className="v5-result-nav" aria-label="ผลลัพธ์การเรียนรู้">
                  <button onClick={() => setLearningFocus(false)}>กลับไปเรียนรู้</button>
                  {learningTools.map(([id, label]) => (
                    <button
                      key={id}
                      className={taskType === id ? 'active' : ''}
                      aria-current={taskType === id ? 'page' : undefined}
                      disabled={taskLocked}
                      onClick={() => {
                        setTaskType(id);
                        setLearningFocus(turns.some((turn) => turn.type === id));
                      }}
                    >
                      {label}
                    </button>
                  ))}
                  <button onClick={() => setLearningFocus(false)}>สร้างใหม่</button>
                </nav>
              </>
            )}
            {tab === 'chat' && (
              <section className="v5-chat-intro">
                <h1>
                  คุยกัน<span className="v5-dot">.</span>
                </h1>
                <div className="v5-chat-art">
                  <span aria-hidden="true" />
                  <BuddyArt pose="chat" />
                </div>
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
                          ? jobStatus(job)
                          : item.error_code
                            ? importMessage(item.error_code)
                            : ''}
                      </span>
                      {job?.state === 'failed' && job.retryable && job.kind === 'import' && (
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
            {tab === 'history' && (
              <ChatHistory
                api={api}
                videos={videos}
                locked={taskLocked}
                open={(id) => onNavigate?.(`/chat/${encodeURIComponent(id)}`)}
                start={() => {
                  resetConversation();
                  navigateTab('chat');
                }}
              />
            )}
            {tab === 'chat' && (
              <div className="chat-source-bar">
                <span>แหล่งข้อมูล · เลือกไว้ {selected.length} คลิป</span>
                <button
                  className="secondary"
                  aria-expanded={sourcesExpanded}
                  aria-controls="chat-sources"
                  onClick={() => setSourcesExpanded((value) => !value)}
                >
                  {sourcesExpanded ? 'ย่อรายการวิดีโอ' : 'เลือกหรือเปลี่ยนวิดีโอ'}
                </button>
              </div>
            )}
            <section
              id="chat-sources"
              className="library-section"
              aria-labelledby="library-title"
              style={{
                display:
                  tab === 'history' || ((tab === 'chat' || tab === 'learn') && !sourcesExpanded)
                    ? 'none'
                    : undefined,
              }}
            >
              <div className="section-heading">
                <div>
                  <h2 id="library-title">
                    {tab === 'home'
                      ? 'เรียนต่อ'
                      : tab === 'library'
                        ? 'ทั้งหมด'
                        : 'แหล่งข้อมูลสำหรับงานนี้'}{' '}
                    <span className="count">{total}</span>
                  </h2>
                  <p>
                    {ready.length} คลิปพร้อมใช้งานในรายการที่โหลด · เลือกไว้ {selected.length} คลิป
                    {hasFilters && ` · ตรงตัวกรอง ${selectedInFilter.length} คลิป`}
                  </p>
                </div>
                <button className="secondary" onClick={() => void refresh()} disabled={loading}>
                  {loading ? 'กำลังโหลด…' : '↻ รีเฟรชคลัง'}
                </button>
              </div>
              <details className="v5-filter-disclosure" open={hasFilters || undefined}>
                <summary>ตัวกรอง</summary>
                <div className={`filters${hasFilters ? ' has-active-filters' : ''}`}>
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
              </details>
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
                  <BuddyArt pose="empty-library" />
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
                        {videoQueryable(video) && video.status !== 'ready'
                          ? 'พร้อมถามจากข้อมูลภาพ'
                          : statusLabels[video.status] || video.status}
                      </span>
                    </div>
                    <div className="video-info">
                      <SourceBadges video={video} />
                      {member && !demo && <MediaEvidence api={api} video={video} />}
                      <div className="video-title-row">
                        <label className="video-select">
                          <input
                            type="checkbox"
                            aria-label={`เลือก ${video.title || video.video_id}`}
                            checked={selected.includes(video.video_id)}
                            disabled={!videoQueryable(video)}
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
                  </div>
                  <button
                    className="primary"
                    aria-label="ถาม Buddy จากวิดีโอที่เลือก"
                    onClick={() => navigateTab('chat')}
                  >
                    ถาม Buddy
                    <Icon name="arrow" />
                  </button>
                  <button className="primary" onClick={() => navigateTab('learn')}>
                    เรียนรู้
                    <UiIcon name="arrow" />
                  </button>
                </div>
              )}
            </section>
            {(tab === 'chat' || tab === 'learn') && (
              <section className="chat-panel" aria-labelledby="task-title">
                <div className="section-heading">
                  <div>
                    <h2 id="task-title">{tab === 'chat' ? 'บทสนทนา' : taskNames[taskType]}</h2>
                  </div>
                  {tab === 'chat' && (
                    <button
                      className="text-button"
                      disabled={taskLocked}
                      onClick={resetConversation}
                    >
                      เริ่มบทสนทนาใหม่
                    </button>
                  )}
                </div>
                {archiveLoading && <p role="status">กำลังเปิดบทสนทนา…</p>}
                {archiveError && (
                  <p className="notice error" role="alert">
                    {archiveError}
                    <button
                      className="text-button"
                      disabled={taskLocked}
                      onClick={() => setArchiveAttempt((value) => value + 1)}
                    >
                      ลองเปิดบทสนทนาอีกครั้ง
                    </button>
                  </p>
                )}
                {tab === 'chat' && viewingHistory && !archiveLoading && !archiveError && (
                  <div className="history-resume" role="status">
                    <span>กำลังอ่านบทสนทนาที่บันทึกไว้</span>
                    <button
                      className="primary"
                      disabled={taskLocked}
                      onClick={() => {
                        setViewingHistory(false);
                        setScopeNotice('พิมพ์คำถามเพื่อสนทนาต่อจากประวัตินี้');
                      }}
                    >
                      ถามต่อในบทสนทนานี้
                    </button>
                  </div>
                )}
                <form
                  onSubmit={submitTask}
                  hidden={
                    (tab === 'chat' && viewingHistory) ||
                    (tab === 'learn' && learningFocus) ||
                    archiveLoading
                  }
                >
                  {tab === 'learn' && (
                    <details className="v5-learning-settings">
                      <summary>ปรับรายละเอียด</summary>
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
                    </details>
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
                    <small id="task-scope-help" role="status">
                      {scopeHelp ||
                        (tab === 'learn' && taskType === 'compare' && selectedInFilter.length < 2
                          ? 'เลือกคลิปที่ตรงตัวกรองอย่างน้อย 2 คลิปเพื่อเปรียบเทียบ'
                          : 'อ้างอิงเฉพาะคลิปที่เลือกและตรงกับตัวกรอง')}
                    </small>
                    <button
                      className="primary"
                      aria-describedby="task-scope-help"
                      disabled={
                        taskLocked ||
                        !!scopeHelp ||
                        (tab === 'chat' && !question.trim()) ||
                        (tab === 'learn' && taskType === 'research' && !question.trim()) ||
                        (tab === 'learn' && taskType === 'compare' && selectedInFilter.length < 2)
                      }
                    >
                      {busy ? 'กำลังทำงาน…' : tab === 'chat' ? 'ส่งคำถาม' : 'เริ่มงาน'}
                      <Icon name="arrow" />
                    </button>
                  </div>
                </form>
                <div className="answer-zone" ref={responseAnchor}>
                  {operation && (
                    <div className="pending-panel" role="status">
                      <BuddyArt pose="states" />
                      <strong>{busy ? 'Buddy กำลังหาคำตอบ…' : 'คำขอนี้ยังรอการตรวจสอบผล'}</strong>
                      <span>{operation.label}</span>
                      {pendingJob && (
                        <span>
                          {pendingJob.state === 'queued'
                            ? 'กำลังรอคิว ระบบจะติดตามผลให้อัตโนมัติ'
                            : jobStatus(pendingJob)}
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
                      className="text-button jump-latest"
                      onClick={() => {
                        latestAnswer.current?.scrollIntoView({
                          behavior: 'instant',
                          block: 'start',
                        });
                        followResults.current = true;
                        setNewResults(false);
                      }}
                    >
                      ไปคำตอบล่าสุด ↓
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
                    {turns
                      .filter((turn) =>
                        tab === 'chat' ? turn.type === 'chat' : turn.type === taskType,
                      )
                      .map((turn, index, visible) => (
                        <article
                          className="turn"
                          key={turn.id}
                          ref={index === visible.length - 1 ? latestAnswer : undefined}
                        >
                          <div className="user-question">{turn.label}</div>
                          <div className="assistant-label">
                            <InteractiveBuddy headOnly active={false} decorative /> Buddy AI
                          </div>
                          {turn.unanswered ? (
                            <p className="notice" role="status">
                              {turn.unanswered} · ยังไม่มีคำตอบที่บันทึกไว้
                            </p>
                          ) : (
                            <ResultView
                              result={turn.result}
                              partial={turn.partial}
                              kind={turn.type}
                            />
                          )}
                        </article>
                      ))}
                    <div ref={resultsEnd} />
                  </div>
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
            {deferred.length > 0 && (
              <section className="deferred-jobs" aria-label="งานที่พักติดตาม">
                <h2>งานที่พักติดตาม</h2>
                {deferred.map((item) => (
                  <article key={item.jobId}>
                    <strong>{item.label}</strong>
                    <p role="status">
                      {jobs[item.jobId!] ? jobStatus(jobs[item.jobId!]) : 'กำลังตรวจสอบสถานะคำขอ'}
                    </p>
                    <button
                      disabled={taskLocked}
                      onClick={() => {
                        setDeferred((previous) =>
                          previous.filter((value) => value.jobId !== item.jobId),
                        );
                        void execute(item, true);
                      }}
                    >
                      ติดตามงานเดิมอีกครั้ง
                    </button>
                    <button onClick={() => void jobAction(item.jobId!, 'cancel')}>
                      ขอยกเลิกงานที่พัก
                    </button>
                  </article>
                ))}
              </section>
            )}
            {Object.values(jobs)
              .filter((job) => job.kind === 'delete' || job.kind === 'detach')
              .map((job) => (
                <div className="notice" key={job.job_id}>
                  {job.kind === 'detach' ? 'นำออกจากคลัง' : 'การลบคลิป'}: {jobStatus(job)}
                  {job.state === 'failed' && job.retryable && job.kind === 'delete' && (
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
          </div>
        </main>
        <nav className="v5-mobile-nav" aria-label="เมนูมือถือ">
          {workspaceMenu.map(([id, label, icon]) => (
            <button
              key={id}
              className={tab === id || (id === 'history' && tab === 'chat') ? 'active' : ''}
              aria-current={tab === id || (id === 'history' && tab === 'chat') ? 'page' : undefined}
              onClick={() => navigateTab(id)}
            >
              <UiIcon name={icon} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        {member && (
          <FloatingBuddy
            open={buddyOpen}
            onOpen={setBuddyOpen}
            videos={filtered}
            selected={selected}
            select={(id) =>
              setSelected((previous) =>
                previous.includes(id)
                  ? previous.filter((value) => value !== id)
                  : [...previous, id],
              )
            }
            question={question}
            change={setQuestion}
            submit={(event) => submitTask(event, 'chat')}
            turns={turns.filter((turn) => turn.type === 'chat')}
            locked={taskLocked || loading || !!libraryError || archiveLoading || viewingHistory}
            busy={busy}
            status={
              operation
                ? `${busy ? 'กำลังทำงาน' : 'รอตรวจสอบผล'}${pendingJob ? ` · ${jobStatus(pendingJob)}` : ''}`
                : ''
            }
            error={taskError || libraryError}
            waiting={deferred.map((item) => ({
              id: item.jobId!,
              label: item.label,
              status: jobs[item.jobId!] ? jobStatus(jobs[item.jobId!]) : 'กำลังตรวจสอบสถานะคำขอ',
              follow: () => {
                setDeferred((previous) => previous.filter((value) => value.jobId !== item.jobId));
                void execute(item, true);
              },
            }))}
            scopeNotice={scopeNotice}
            scopeHelp={scopeHelp}
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
    </EvidenceContext.Provider>
  );
}

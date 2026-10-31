import type {
  Accepted,
  Answer,
  Artifact,
  ImportItem,
  Job,
  Page,
  ProgressEvent,
  Video,
  EvidenceBridge,
  FrameReference,
  TaskResult,
} from './types';
import { terminal } from './domain';

export class ApiError extends Error {
  constructor(
    message: string,
    public code = 'network_error',
    public retryable = true,
    public requestId?: string,
    public jobId?: string,
    public status?: number,
    public retryAfter?: string,
  ) {
    super(message);
  }
}
export type Transport = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
export type TaskResponse = { status: 200; data: Answer } | { status: 202; data: Accepted };
export interface ApiSecurity {
  csrf: () => { header: string; token: string };
  onSessionExpired: () => void;
}
export class Api {
  chatPolicyAvailable = false;
  chatPolicyUnsupported = false;
  get authenticated() {
    return !!this.security;
  }
  onMode?: (mode: string) => void;
  private controllers = new Set<AbortController>();
  private disposed = false;
  private mediaSnapshots = new Map<string, import('./types').MediaEvidenceData>();
  constructor(
    private base: string,
    private transport: Transport = (input, init) => fetch(input, init),
    private timeoutMs = 75000,
    private security?: ApiSecurity,
    private evidence?: EvidenceBridge,
  ) {}
  private mapCitation = (value: import('./types').Citation) => ({
    ...value,
    presentation: this.evidence?.citation(value),
  });
  private mapArtifact = (value: Artifact): Artifact => ({
    ...value,
    citations: value.citations.map(this.mapCitation),
  });
  private mapResult = (value: TaskResult): TaskResult => ({
    ...value,
    visualCoverage: this.evidence?.coverage(value),
    citations: value.citations?.map(this.mapCitation),
    artifacts: value.artifacts?.map(this.mapArtifact),
  });
  loadFrame = async (frame: FrameReference, signal: AbortSignal): Promise<Blob> => {
    if (this.disposed) throw new DOMException('Session ended', 'AbortError');
    if (frame.assetId) {
      const evidence =
        this.mediaSnapshots.get(frame.videoId) || (await this.mediaEvidence(frame.videoId, signal));
      const match = evidence.evidence.some(
        (item) =>
          item.frame_id === frame.frameId &&
          item.asset_id === frame.assetId &&
          item.evidence_version === frame.evidenceVersion &&
          item.timestamp_seconds === frame.timeSeconds,
      );
      if (
        evidence.generation !== frame.generation ||
        !match ||
        !/^[a-f0-9]{64}$/.test(frame.assetId)
      )
        throw new ApiError('หลักฐานภาพเปลี่ยนแปลงหรือไม่มีสิทธิ์เปิด', 'source_changed', false);
      return this.readEvidenceAsset(`/api/media/assets/${frame.assetId}`, signal);
    }
    if (!this.evidence)
      throw new ApiError(
        'ยังรอ API หลักฐานภาพที่ตรวจสิทธิ์',
        'evidence_contract_unavailable',
        false,
      );
    return this.evidence.asset(frame, signal, this.readEvidenceAsset);
  };
  private readEvidenceAsset = async (path: string, signal: AbortSignal): Promise<Blob> => {
    if (this.disposed) throw new DOMException('Session ended', 'AbortError');
    const base = new URL(this.base || '/', 'http://local.invalid');
    const target = new URL(path, base);
    if (
      !path.startsWith('/api/') ||
      /[\\\r\n#]/.test(path) ||
      target.origin !== base.origin ||
      !target.pathname.startsWith('/api/')
    )
      throw new ApiError('เส้นทางภาพไม่ถูกต้อง', 'invalid_asset', false);
    signal.throwIfAborted();
    const controller = new AbortController();
    this.controllers.add(controller);
    const abort = () => controller.abort();
    signal.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(abort, this.timeoutMs);
    try {
      const response = await this.transport(`${this.base}${path}`, {
        credentials: this.security ? 'include' : 'same-origin',
        cache: 'no-store',
        redirect: 'error',
        signal: controller.signal,
        headers: { Accept: 'image/png,image/jpeg,image/webp,image/avif' },
      });
      if (response.status === 401) this.security?.onSessionExpired();
      if (!response.ok)
        throw new ApiError(
          response.status === 403 || response.status === 404
            ? 'ไม่มีสิทธิ์ดูภาพ หรือภาพใช้ไม่ได้แล้ว'
            : 'โหลดภาพไม่สำเร็จ',
          'asset_unavailable',
          false,
          undefined,
          undefined,
          response.status,
        );
      if (!/^image\/(png|jpeg|webp|avif)(;|$)/i.test(response.headers.get('Content-Type') || ''))
        throw new ApiError('ข้อมูลภาพไม่ถูกต้อง', 'invalid_asset', false);
      const blob = await response.blob();
      if (blob.size > 10 * 1024 * 1024)
        throw new ApiError('ภาพมีขนาดใหญ่เกินไป', 'invalid_asset', false);
      return blob;
    } finally {
      clearTimeout(timer);
      this.controllers.delete(controller);
      signal.removeEventListener('abort', abort);
    }
  };
  dispose() {
    this.disposed = true;
    this.mediaSnapshots.clear();
    this.controllers.forEach((controller) => controller.abort());
    this.controllers.clear();
  }
  async request<T>(path: string, init: RequestInit = {}): Promise<{ status: number; data: T }> {
    if (this.disposed) throw new DOMException('Session ended', 'AbortError');
    init.signal?.throwIfAborted();
    const controller = new AbortController();
    this.controllers.add(controller);
    const mutating = !['GET', 'HEAD', 'OPTIONS'].includes((init.method || 'GET').toUpperCase());
    const csrf = mutating ? this.security?.csrf() : undefined;
    if (this.security && mutating && (!csrf?.token || !csrf.header)) {
      this.controllers.delete(controller);
      throw new ApiError('กรุณาเข้าสู่ระบบอีกครั้ง', 'csrf_missing', false);
    }
    const cancel = () => controller.abort();
    init.signal?.addEventListener('abort', cancel, { once: true });
    const timer = setTimeout(cancel, this.timeoutMs);
    try {
      const response = await this.transport(`${this.base}${path}`, {
        ...init,
        credentials: this.security ? 'include' : init.credentials || 'same-origin',
        signal: controller.signal,
        headers: {
          Accept: 'application/json',
          ...(init.body ? { 'Content-Type': 'application/json' } : {}),
          ...init.headers,
          ...(csrf ? { [csrf.header]: csrf.token } : {}),
        },
      });
      const mode = response.headers.get('X-Adapter-Mode');
      if (mode) this.onMode?.(mode);
      if (response.status === 401) this.security?.onSessionExpired();
      const data = await response.json().catch(() => {
        throw new ApiError(
          'เซิร์ฟเวอร์ส่งข้อมูลที่อ่านไม่ได้',
          'invalid_response',
          false,
          undefined,
          undefined,
          response.status,
          response.headers.get('Retry-After') || undefined,
        );
      });
      if (!response.ok) {
        const e = data?.error;
        throw new ApiError(
          e?.message || `คำขอไม่สำเร็จ (HTTP ${response.status})`,
          e?.code || 'http_error',
          [401, 403].includes(response.status) ? false : (e?.retryable ?? response.status >= 500),
          e?.request_id || response.headers.get('X-Request-ID') || undefined,
          e?.job_id,
          response.status,
          response.headers.get('Retry-After') || undefined,
        );
      }
      if (!data || typeof data !== 'object')
        throw new ApiError('รูปแบบข้อมูลไม่ตรง API', 'invalid_response', false);
      if (typeof data.mode === 'string') this.onMode?.(data.mode);
      return { status: response.status, data: data as T };
    } catch (error) {
      if (init.signal?.aborted || this.disposed) throw new DOMException('Aborted', 'AbortError');
      if (error instanceof ApiError) throw error;
      throw new ApiError(
        controller.signal.aborted
          ? 'การเชื่อมต่อใช้เวลานานเกินไป ลองติดตามผลหรือส่งคำขอเดิมซ้ำ'
          : 'เชื่อมต่อ API ไม่ได้ ตรวจสอบว่า backend เปิดอยู่และอนุญาต origin ของเว็บ',
      );
    } finally {
      clearTimeout(timer);
      this.controllers.delete(controller);
      init.signal?.removeEventListener('abort', cancel);
    }
  }
  async feedback(id: string, signal?: AbortSignal) {
    return (
      await this.request<{
        message_id: string;
        feedback: import('./feedbackSession').WireFeedback | null;
      }>(`/api/messages/${encodeURIComponent(id)}/feedback`, { signal, cache: 'no-store' })
    ).data;
  }
  async saveFeedback(
    id: string,
    value: import('./feedbackSession').WireFeedback | null,
    signal?: AbortSignal,
  ) {
    return (
      await this.request<{
        message_id: string;
        feedback: import('./feedbackSession').WireFeedback | null;
      }>(`/api/messages/${encodeURIComponent(id)}/feedback`, {
        method: value ? 'PUT' : 'DELETE',
        body: value ? JSON.stringify(value) : undefined,
        signal,
      })
    ).data;
  }
  async videos(offset = 0, signal?: AbortSignal) {
    const { data } = await this.request<Page<Video>>(`/api/videos?limit=50&offset=${offset}`, {
      signal,
    });
    if (!Array.isArray(data.items) || !Number.isInteger(data.total))
      throw new ApiError('รายการคลิปไม่ตรง API', 'invalid_response', false);
    return {
      ...data,
      items: data.items.map((video) => ({ ...video, presentation: this.evidence?.source(video) })),
    };
  }
  async mediaEvidence(videoId: string, signal?: AbortSignal) {
    if (!/^[\w-]{11}$/.test(videoId))
      throw new ApiError('รหัสคลิปไม่ถูกต้อง', 'invalid_source', false);
    const { data } = await this.request<import('./types').MediaEvidenceData>(
      `/api/v2/videos/${videoId}/evidence`,
      { signal },
    );
    if (
      data.contract_version !== 2 ||
      data.video_id !== videoId ||
      !Number.isInteger(data.generation) ||
      data.generation < 1 ||
      !Array.isArray(data.evidence) ||
      data.evidence.length > 200 ||
      data.evidence.some(
        (item) =>
          !/^[a-f0-9]{64}$/.test(item.frame_id) ||
          !/^[a-f0-9]{64}$/.test(item.asset_id) ||
          !/^[a-f0-9]{64}$/.test(item.evidence_version) ||
          !Number.isFinite(item.timestamp_seconds) ||
          item.timestamp_seconds < 0 ||
          typeof item.text !== 'string' ||
          !['ocr', 'visual'].includes(item.kind),
      )
    )
      throw new ApiError('ข้อมูลภาพไม่ตรงกับคลิป', 'invalid_response', false);
    if (this.mediaSnapshots.size >= 50)
      this.mediaSnapshots.delete(this.mediaSnapshots.keys().next().value!);
    this.mediaSnapshots.set(videoId, data);
    return data;
  }
  async memberJobs(includeCompleted = false, offset = 0, signal?: AbortSignal) {
    const { data } = await this.request<Page<import('./types').RecoverableJob>>(
      `/api/member/jobs?limit=50&offset=${offset}&include_completed=${includeCompleted}`,
      { signal },
    );
    if (
      !Array.isArray(data.items) ||
      !Number.isInteger(data.total) ||
      data.total < 0 ||
      data.items.some(
        (job) =>
          !job ||
          typeof job.job_id !== 'string' ||
          !job.request ||
          typeof job.request !== 'object' ||
          !Array.isArray(job.sources) ||
          job.sources.some((source) => !source || !/^[\w-]{11}$/.test(source.video_id)),
      )
    )
      throw new ApiError('รายการงานไม่ถูกต้อง', 'invalid_response', false);
    return data;
  }
  async workerStatus(signal?: AbortSignal) {
    return (
      await this.request<{ status: string; ready: boolean }>('/api/worker-status', { signal })
    ).data;
  }
  async importVideos(urls: string[], signal?: AbortSignal) {
    const { data } = await this.request<{ jobs: ImportItem[]; mode: string }>(
      '/api/videos/import',
      { method: 'POST', body: JSON.stringify({ urls }), signal },
    );
    if (!Array.isArray(data.jobs))
      throw new ApiError('ผลนำเข้าไม่ตรง API', 'invalid_response', false);
    return data;
  }
  async job(id: string, signal?: AbortSignal): Promise<Job> {
    const { data } = await this.request<Job>(`/api/jobs/${encodeURIComponent(id)}`, { signal });
    if (
      !data.job_id ||
      !['queued', 'running', 'paused', 'completed', 'partial', 'failed', 'cancelled'].includes(
        data.state,
      )
    ) {
      throw new ApiError('สถานะงานไม่ตรง API', 'invalid_response', false);
    }
    return {
      ...data,
      presentation: this.evidence?.job(data),
      result: data.result ? this.mapResult(data.result) : null,
    };
  }
  async submit(
    path: string,
    payload: object,
    key: string,
    signal?: AbortSignal,
  ): Promise<TaskResponse> {
    const response = await this.request<Answer | Accepted>(path, {
      method: 'POST',
      headers: { 'Idempotency-Key': key },
      body: JSON.stringify(payload),
      signal,
    });
    if (response.status === 202 && 'job_id' in response.data && response.data.job_id)
      return { status: 202, data: response.data as Accepted };
    if (
      response.status === 200 &&
      'answer' in response.data &&
      typeof response.data.answer === 'string'
    )
      return { status: 200, data: this.mapResult(response.data as Answer) as Answer };
    throw new ApiError('ผลคำขอไม่ตรง API', 'invalid_response', false);
  }
  async resumeChat(id: string, original: object, confirm: (message: string) => boolean) {
    const path = `/api/jobs/${encodeURIComponent(id)}/resume`;
    const post = (body: object) =>
      this.request<Accepted>(path, { method: 'POST', body: JSON.stringify(body) });
    try {
      return (await post({})).data;
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== 'moderation_confirmation_required')
        throw error;
    }
    const { data } = await this.request<{
      decision: 'allow' | 'warn' | 'block';
      message: string;
      acknowledgment_token?: string;
    }>('/api/chat/check', {
      method: 'POST',
      body: JSON.stringify({ ...original, moderation_token: undefined }),
    });
    if (data.decision === 'block') throw new ApiError(data.message, 'moderation_blocked', false);
    if (data.decision === 'warn') {
      if (!data.acknowledgment_token || !confirm(data.message)) return null;
      return (await post({ moderation_token: data.acknowledgment_token })).data;
    }
    if (data.decision !== 'allow')
      throw new ApiError('ตรวจข้อความไม่สำเร็จ', 'invalid_response', false);
    return (await post({})).data;
  }
  async cancel(id: string) {
    return (
      await this.request<Job>(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
    ).data;
  }
  async retry(id: string) {
    return (
      await this.request<Accepted>(`/api/jobs/${encodeURIComponent(id)}/retry`, { method: 'POST' })
    ).data;
  }
  async deleteVideo(id: string) {
    return (
      await this.request<Accepted>(`/api/videos/${encodeURIComponent(id)}`, { method: 'DELETE' })
    ).data;
  }
  async history(id: string, offset = 0, signal?: AbortSignal) {
    const { data } = await this.request<import('./types').ConversationPage>(
      `/api/conversations/${encodeURIComponent(id)}?limit=50&offset=${offset}`,
      { signal, cache: 'no-store' },
    );
    if (
      !Array.isArray(data.messages) ||
      !Number.isInteger(data.total) ||
      data.conversation_id !== id
    )
      throw new ApiError('ประวัติสนทนาไม่ตรง API', 'invalid_response', false);
    return {
      ...data,
      messages: data.messages.map((message) => ({
        ...message,
        citations: message.citations.map(this.mapCitation),
      })),
    };
  }
  async conversations(query = '', offset = 0, signal?: AbortSignal) {
    const params = new URLSearchParams({ q: query, limit: '20', offset: String(offset) });
    const { data } = await this.request<Page<import('./types').ConversationSummary>>(
      `/api/conversations?${params}`,
      { signal, cache: 'no-store' },
    );
    if (!Array.isArray(data.items) || !Number.isInteger(data.total))
      throw new ApiError('โหลดประวัติแชตไม่ได้ กรุณาลองใหม่', 'invalid_response', false);
    return data;
  }
  async research(id: string, after = 0, signal?: AbortSignal) {
    return (
      await this.request<Job & { events: ProgressEvent[] }>(
        `/api/research/${encodeURIComponent(id)}?after_event_id=${after}&limit=100`,
        { signal },
      )
    ).data;
  }
  async artifact(id: string, signal?: AbortSignal) {
    return this.mapArtifact(
      (
        await this.request<Artifact>(`/api/learning-artifacts/${encodeURIComponent(id)}`, {
          signal,
        })
      ).data,
    );
  }
}

export function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', abort);
      resolve();
    }, ms);
    if (signal?.aborted) abort();
    else signal?.addEventListener('abort', abort, { once: true });
  });
}
// Sequential polling: no overlapping requests, no further reads after a terminal state.
// A client time limit pauses observation; it does not claim the server job failed.
export async function pollJob(
  api: Api,
  id: string,
  onUpdate: (job: Job) => void | Promise<void>,
  signal: AbortSignal,
  options = { intervalMs: 750, maxMs: 600000 },
): Promise<Job> {
  const started = Date.now();
  let failures = 0;
  while (true) {
    signal.throwIfAborted();
    try {
      const job = await api.job(id, signal);
      await onUpdate(job);
      failures = 0;
      if (terminal(job.state)) return job;
    } catch (error) {
      if (!(error instanceof ApiError) || !error.retryable || ++failures >= 3) throw error;
    }
    if (Date.now() - started >= options.maxMs)
      throw new ApiError(
        'พักการติดตามผลแล้ว งานอาจยังทำต่อบนเซิร์ฟเวอร์ กดติดตามผลอีกครั้งได้',
        'polling_paused',
      );
    await delay(options.intervalMs * Math.max(1, failures * 2), signal);
  }
}

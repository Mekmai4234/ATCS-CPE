import type {
  Accepted,
  Answer,
  Artifact,
  ImportItem,
  Job,
  Page,
  ProgressEvent,
  Video,
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
  onMode?: (mode: string) => void;
  private controllers = new Set<AbortController>();
  private disposed = false;
  constructor(
    private base: string,
    private transport: Transport = (input, init) => fetch(input, init),
    private timeoutMs = 75000,
    private security?: ApiSecurity,
  ) {}
  dispose() {
    this.disposed = true;
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
        credentials: this.security ? 'include' : 'same-origin',
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
        throw new ApiError('เซิร์ฟเวอร์ส่งข้อมูลที่อ่านไม่ได้', 'invalid_response', false);
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
  async videos(offset = 0, signal?: AbortSignal) {
    const { data } = await this.request<Page<Video>>(`/api/videos?limit=50&offset=${offset}`, {
      signal,
    });
    if (!Array.isArray(data.items) || !Number.isInteger(data.total))
      throw new ApiError('รายการคลิปไม่ตรง API', 'invalid_response', false);
    return data;
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
      !['queued', 'running', 'completed', 'partial', 'failed', 'cancelled'].includes(data.state)
    ) {
      throw new ApiError('สถานะงานไม่ตรง API', 'invalid_response', false);
    }
    return data;
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
      return { status: 200, data: response.data as Answer };
    throw new ApiError('ผลคำขอไม่ตรง API', 'invalid_response', false);
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
  async research(id: string, after = 0, signal?: AbortSignal) {
    return (
      await this.request<Job & { events: ProgressEvent[] }>(
        `/api/research/${encodeURIComponent(id)}?after_event_id=${after}&limit=100`,
        { signal },
      )
    ).data;
  }
  async artifact(id: string, signal?: AbortSignal) {
    return (
      await this.request<Artifact>(`/api/learning-artifacts/${encodeURIComponent(id)}`, { signal })
    ).data;
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
  options = { intervalMs: 1500, maxMs: 600000 },
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

import { describe, expect, it, vi } from 'vitest';
import { Api, ApiError, pollJob } from '../src/api';
import { demoTransport } from '../src/demo';
import type { Job } from '../src/types';

const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const snapshot = (state: Job['state']): Job => ({
  job_id: 'j1',
  state,
  stage: state,
  kind: 'chat',
  video_id: null,
  attempt_count: 1,
  max_attempts: 3,
  cancel_requested: false,
  result: null,
  retryable: false,
  error_code: null,
  mode: 'fixture',
});
describe('HTTP contract', () => {
  it.each([200, 202])('supports chat HTTP %i', async (status) => {
    const transport = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      response(
        status === 200
          ? { answer: 'Answer', status: 'answered' }
          : { job_id: 'j1', state: 'queued' },
        status,
      ),
    );
    const api = new Api('http://api.test', transport);
    const result = await api.submit('/api/chat', { question: 'Q' }, 'stable-key');
    expect(result.status).toBe(status);
    expect(new Headers(transport.mock.calls[0]?.[1]?.headers).get('Idempotency-Key')).toBe(
      'stable-key',
    );
  });
  it('preserves structured error IDs and retryability', async () => {
    const api = new Api('http://api.test', async () =>
      response(
        {
          error: {
            code: 'source_changed',
            message: 'Changed',
            retryable: false,
            request_id: 'req1',
            job_id: 'j1',
          },
        },
        409,
      ),
    );
    await expect(api.submit('/api/chat', {}, 'key')).rejects.toMatchObject({
      code: 'source_changed',
      retryable: false,
      requestId: 'req1',
      jobId: 'j1',
    });
  });
  it('does not silently fall back to demo on a network error', async () => {
    const api = new Api('http://api.test', async () => {
      throw new TypeError('offline');
    });
    await expect(api.videos()).rejects.toBeInstanceOf(ApiError);
  });
  it('rejects malformed accepted responses', async () => {
    const api = new Api('http://api.test', async () => response({ state: 'queued' }, 202));
    await expect(api.submit('/api/chat', {}, 'key')).rejects.toMatchObject({
      code: 'invalid_response',
    });
  });
  it('propagates abort without converting it to retryable network failure', async () => {
    const controller = new AbortController();
    controller.abort();
    const transport = vi.fn();
    const api = new Api('http://api.test', transport);
    await expect(api.videos(0, controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    expect(transport).not.toHaveBeenCalled();
  });
});
describe('sequential job polling', () => {
  it.each(['completed', 'partial', 'failed', 'cancelled'] as const)(
    'stops at %s',
    async (state) => {
      const read = vi
        .fn()
        .mockResolvedValueOnce(snapshot('running'))
        .mockResolvedValueOnce(snapshot(state));
      const api = { job: read } as unknown as Api;
      const updates = vi.fn();
      const result = await pollJob(api, 'j1', updates, new AbortController().signal, {
        intervalMs: 1,
        maxMs: 1000,
      });
      expect(result.state).toBe(state);
      expect(read).toHaveBeenCalledTimes(2);
      expect(updates).toHaveBeenCalledTimes(2);
    },
  );
  it('bounds retries for failed GET requests', async () => {
    const read = vi.fn().mockRejectedValue(new ApiError('offline'));
    await expect(
      pollJob({ job: read } as unknown as Api, 'j1', () => {}, new AbortController().signal, {
        intervalMs: 1,
        maxMs: 1000,
      }),
    ).rejects.toThrow('offline');
    expect(read).toHaveBeenCalledTimes(3);
  });
  it('never retries a permanent polling error', async () => {
    const read = vi.fn().mockRejectedValue(new ApiError('gone', 'not_found', false));
    await expect(
      pollJob({ job: read } as unknown as Api, 'j1', () => {}, new AbortController().signal),
    ).rejects.toThrow('gone');
    expect(read).toHaveBeenCalledTimes(1);
  });
  it('aborts a waiting observer before another HTTP request', async () => {
    const controller = new AbortController();
    const read = vi.fn().mockResolvedValue(snapshot('running'));
    const promise = pollJob(
      { job: read } as unknown as Api,
      'j1',
      () => {
        controller.abort();
      },
      controller.signal,
      { intervalMs: 100, maxMs: 1000 },
    );
    await expect(promise).rejects.toMatchObject({ name: 'AbortError' });
    expect(read).toHaveBeenCalledTimes(1);
  });
});
describe('explicit demo', () => {
  it('returns all three import outcomes and no-transcript separately from job completion', async () => {
    const api = new Api('http://demo.test', demoTransport());
    const result = await api.importVideos([
      'https://youtu.be/NoCaption01',
      'https://youtu.be/dQw4w9WgXcQ',
      'invalid',
    ]);
    expect(result.jobs.map((j) => j.outcome)).toEqual(['accepted', 'existing', 'rejected']);
    const id = result.jobs[0].job_id!;
    await api.job(id);
    const final = await api.job(id);
    expect(final).toMatchObject({ state: 'completed', stage: 'no_transcript' });
  });
  it('reuses same-key same-input chat and rejects changed input', async () => {
    const api = new Api('http://demo.test', demoTransport());
    const body = { question: 'RAG', scope: { video_ids: ['dQw4w9WgXcQ'] } };
    const first = await api.submit('/api/chat', body, 'same');
    const second = await api.submit('/api/chat', body, 'same');
    expect(second).toEqual(first);
    await expect(
      api.submit('/api/chat', { ...body, question: 'changed' }, 'same'),
    ).rejects.toMatchObject({ code: 'idempotency_conflict' });
  });
});

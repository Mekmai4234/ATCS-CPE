import { describe, expect, it, vi } from 'vitest';
import { Api } from '../src/api';
import { buildScope, jobShouldPark, jobStatus, videoQueryable } from '../src/domain';
import { reconcileSources, snapshotSources } from '../src/sources';
import { validFrame } from '../src/Evidence';
import { visualFixture } from './visual-fixture';
import type { Video, FrameReference, Job } from '../src/types';
const video = {
  video_id: 'VisualDemo1',
  status: 'no_transcript',
  generation: 1,
  indexed_version: null,
} as Video;
const json = (value: unknown, status = 200, headers = {}) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
const frame: FrameReference = {
  videoId: video.video_id,
  generation: 1,
  evidenceVersion: 'visual-v1',
  frameId: 'frame-ocr',
  timeSeconds: 14,
};
describe('visual integration boundary', () => {
  it('does not trust unsolicited presentation data or enable visual-only sources without the adapter', async () => {
    const api = new Api('', async () =>
      json({
        items: [{ ...video, presentation: visualFixture.source(video) }],
        total: 1,
        limit: 50,
        offset: 0,
      }),
    );
    const data = await api.videos();
    expect(data.items[0].presentation).toBeUndefined();
    expect(videoQueryable(data.items[0])).toBe(false);
    await expect(api.loadFrame(frame, new AbortController().signal)).rejects.toMatchObject({
      code: 'evidence_contract_unavailable',
    });
  });
  it('permits visual-only scope only after an explicit bridge confirms queryable evidence', async () => {
    const api = new Api(
      '',
      async () => json({ items: [video], total: 1, limit: 50, offset: 0 }),
      1000,
      undefined,
      visualFixture,
    );
    const data = await api.videos();
    expect(videoQueryable(data.items[0])).toBe(true);
    expect(buildScope([video.video_id], data.items, '', '', '').video_ids).toEqual([
      video.video_id,
    ]);
    expect(
      snapshotSources(data.items, {
        video_ids: [video.video_id],
        channel_ids: [],
        date_from: null,
        date_to: null,
      })[0],
    ).toMatchObject({ evidenceVersion: 'visual-v1', indexed_version: null });
  });
  it('invalidates a changed visual evidence version without inventing a transcript version', () => {
    const current = { ...video, presentation: visualFixture.source(video)! };
    const source = {
      video_id: video.video_id,
      generation: 1,
      indexed_version: null,
      evidenceVersion: 'visual-old',
    };
    expect(
      reconcileSources(
        {
          citations: [
            {
              citation_id: 'c',
              chunk_id: 'e',
              video_id: video.video_id,
              title: 'Frame',
              start_seconds: 14,
              end_seconds: 15,
              url: '',
            },
          ],
        },
        [source],
        { videos: [current] },
      ).citations?.[0].source_available,
    ).toBe(false);
  });
  it.each([403, 404])('does not retry denied or missing images (%i)', async (status) => {
    const send = vi.fn(async () => json({}, status));
    const api = new Api('http://api.test', send, 1000, undefined, visualFixture);
    await expect(api.loadFrame(frame, new AbortController().signal)).rejects.toMatchObject({
      status,
      retryable: false,
    });
    expect(send).toHaveBeenCalledTimes(1);
  });
  it('includes cookies, disables cache/redirects and rejects unsafe MIME', async () => {
    const expired = vi.fn();
    const send = vi.fn(
      async () => new Response('<svg/>', { headers: { 'Content-Type': 'image/svg+xml' } }),
    );
    const api = new Api(
      'http://api.test',
      send,
      1000,
      { csrf: () => ({ header: 'X-CSRF', token: 't' }), onSessionExpired: expired },
      visualFixture,
    );
    await expect(api.loadFrame(frame, new AbortController().signal)).rejects.toMatchObject({
      code: 'invalid_asset',
    });
    expect(send.mock.calls[0]).toBeDefined();
    const init = (send.mock.calls as unknown as [string, RequestInit][])[0][1];
    expect(init).toMatchObject({ credentials: 'include', cache: 'no-store', redirect: 'error' });
  });
  it('returns to login on an image 401 and aborts images on disposal', async () => {
    const expired = vi.fn();
    const security = { csrf: () => ({ header: 'X-CSRF', token: 't' }), onSessionExpired: expired };
    const api = new Api('', async () => json({}, 401), 1000, security, visualFixture);
    await expect(api.loadFrame(frame, new AbortController().signal)).rejects.toMatchObject({
      status: 401,
    });
    expect(expired).toHaveBeenCalledOnce();
    const waiting = new Api(
      '',
      (_url, init) =>
        new Promise((_resolve, reject) =>
          init?.signal?.addEventListener('abort', () =>
            reject(new DOMException('Aborted', 'AbortError')),
          ),
        ),
      1000,
      security,
      visualFixture,
    );
    const pending = waiting.loadFrame(frame, new AbortController().signal);
    waiting.dispose();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });
  it('preserves backend Retry-After without a frontend reset countdown', async () => {
    const api = new Api('', async () =>
      json({ error: { code: 'generation_rate_limited' } }, 429, { 'Retry-After': '90' }),
    );
    await expect(api.submit('/api/chat', {}, 'key')).rejects.toMatchObject({
      status: 429,
      retryAfter: '90',
    });
  });
  it('separates 429/503 and only displays a retry time explicitly supplied by the adapter', () => {
    const quota = {
      state: 'queued',
      stage: 'queued',
      error_code: 'generation_rate_limited',
    } as Job;
    expect(jobStatus(quota)).toContain('มีคำขอจำนวนมาก');
    expect(jobStatus(quota)).not.toMatch(/Gemini|429|โควตา/);
    expect(jobStatus(quota)).not.toContain('ลองอีกครั้งได้หลัง');
    expect(jobStatus({ ...quota, error_code: 'generation_provider_busy' })).toContain(
      'ไม่พร้อมให้บริการชั่วคราว',
    );
    expect(
      jobStatus({
        ...quota,
        presentation: { stage: 'quota_paused', retryAt: '2026-10-25T06:00:00Z' },
      }),
    ).toContain('ลองอีกครั้งได้หลัง');
  });
  it('rejects invalid frame identity, times and generations', () => {
    expect(validFrame(frame)).toBe(true);
    expect(validFrame({ ...frame, timeSeconds: NaN })).toBe(false);
    expect(validFrame({ ...frame, generation: 0 })).toBe(false);
    expect(validFrame({ ...frame, videoId: 'https://evil.test' })).toBe(false);
  });
  it('understands native backend waiting metadata without calling estimates provider reset times', () => {
    const native = {
      state: 'queued',
      stage: 'queued',
      error_code: 'quota_wait',
      wait: { time_source: 'estimate', estimated_retry_at: '2026-10-25T06:00:00Z' },
    } as Job;
    expect(jobShouldPark(native)).toBe(true);
    expect(jobStatus(native)).toContain('เวลาประมาณการของระบบ');
    expect(jobStatus(native)).not.toContain('ลองอีกครั้งได้หลัง');
    const known = {
      ...native,
      wait: { time_source: 'provider' as const, retry_at: '2026-10-25T06:00:00Z' },
    };
    expect(jobStatus(known)).toContain('ลองอีกครั้งได้หลัง');
  });
  it('accepts a native paused job and parks it without treating it as a completed answer', async () => {
    const api = new Api('', async () =>
      json({
        job_id: 'paused',
        state: 'paused',
        stage: 'paused',
        error_code: 'free_tier_unverified',
        result: null,
      }),
    );
    const paused = await api.job('paused');
    expect(jobShouldPark(paused)).toBe(true);
    expect(paused.result).toBeNull();
    expect(jobStatus(paused)).toContain('ผู้ช่วย AI ยังไม่พร้อมให้บริการ');
  });
  it('never enables deleted sources even with stale visual readiness', () => {
    expect(
      videoQueryable({ ...video, status: 'deleted', presentation: visualFixture.source(video) }),
    ).toBe(false);
    expect(
      videoQueryable({ ...video, status: 'deleting', presentation: visualFixture.source(video) }),
    ).toBe(false);
  });
  it('disables a citation whose frame belongs to another evidence version or generation', () => {
    const current = { ...video, presentation: visualFixture.source(video)! };
    const citation = {
      citation_id: 'frame-ocr',
      video_id: video.video_id,
    } as import('../src/types').Citation;
    const presentation = visualFixture.citation(citation)!;
    const sources = [{ video_id: video.video_id, generation: 1, evidenceVersion: 'visual-v1' }];
    for (const frame of [
      { ...presentation.frame!, generation: 2 },
      { ...presentation.frame!, evidenceVersion: 'old' },
    ]) {
      const result = reconcileSources(
        { citations: [{ ...citation, presentation: { ...presentation, frame } }] },
        sources,
        { videos: [current] },
      );
      expect(result.citations?.[0].source_available).toBe(false);
    }
  });
});

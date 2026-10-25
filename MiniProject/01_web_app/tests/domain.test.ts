import { describe, expect, it } from 'vitest';
import { buildScope, citationUrl, jobWarning, terminal, videoIdFromUrl } from '../src/domain';
import type { Citation, Job, Video } from '../src/types';

const video = {
  video_id: 'dQw4w9WgXcQ',
  title: 'Test',
  channel_id: 'c1',
  published_at: '2026-10-01',
  status: 'ready',
} as Video;
describe('YouTube and citation validation', () => {
  it.each([
    'https://youtu.be/dQw4w9WgXcQ',
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    'https://m.youtube.com/watch?v=dQw4w9WgXcQ',
  ])('accepts supported URL %s', (url) => {
    expect(videoIdFromUrl(url)).toBe(video.video_id);
  });
  it.each([
    'http://youtu.be/dQw4w9WgXcQ',
    'https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ',
    'https://youtu.be/dQw4w9WgXcQ/extra',
    'https://youtu.be:8443/dQw4w9WgXcQ',
    'https://user@youtu.be/dQw4w9WgXcQ',
    'javascript:alert(1)',
    'https://youtube.com/playlist?list=123',
  ])('rejects unsupported URL %s', (url) => {
    expect(videoIdFromUrl(url)).toBeNull();
  });
  it('builds citation URL from validated ID/time, ignoring returned URL', () => {
    expect(
      citationUrl({
        video_id: video.video_id,
        start_seconds: 14.9,
        end_seconds: 20,
        url: 'javascript:alert(1)',
      } as Citation),
    ).toBe('https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=14s');
  });
  it.each([
    { start_seconds: -1 },
    { end_seconds: 2 },
    { start_seconds: NaN },
    { video_id: 'bad' },
    { source_available: false },
  ])('disables invalid/unavailable citations %j', (patch) => {
    expect(
      citationUrl({
        video_id: video.video_id,
        start_seconds: 3,
        end_seconds: 9,
        ...patch,
      } as Citation),
    ).toBeNull();
  });
});
describe('source scope', () => {
  it('requires explicit ready videos', () => {
    expect(() => buildScope([], [video], '', '', '')).toThrow();
    expect(() =>
      buildScope([video.video_id], [{ ...video, status: 'indexing' }], '', '', ''),
    ).toThrow();
  });
  it('preserves selection and filters without widening scope or adding playlists', () => {
    expect(buildScope([video.video_id], [video], 'c1', '2026-10-01', '2026-10-01')).toEqual({
      video_ids: [video.video_id],
      channel_ids: ['c1'],
      date_from: '2026-10-01',
      date_to: '2026-10-01',
    });
  });
  it('rejects reversed ranges and empty intersections', () => {
    expect(() => buildScope([video.video_id], [video], '', '2026-10-02', '2026-10-01')).toThrow();
    expect(() => buildScope([video.video_id], [video], 'other', '', '')).toThrow();
    expect(() =>
      buildScope([video.video_id], [{ ...video, published_at: null }], '', '2026-01-01', ''),
    ).toThrow();
  });
  it('treats all four terminal job states as terminal', () => {
    expect(['completed', 'partial', 'failed', 'cancelled'].every(terminal)).toBe(true);
    expect(terminal('running')).toBe(false);
    expect(terminal('no_transcript')).toBe(false);
  });
  it('explains truncated answers without presenting them as completed', () => {
    const job = { state: 'failed', error_code: 'generation_output_truncated' } as Job;
    expect(jobWarning(job)).toContain('ถูกตัด');
    expect(jobWarning({ ...job, state: 'completed' })).toBeNull();
    expect(jobWarning({ ...job, error_code: 'invalid_citation' })).toBe(
      'ทำรายการไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
    );
  });
  it('explains transcript size and availability failures', () => {
    expect(jobWarning({ state: 'failed', error_code: 'transcript_too_large' } as Job)).toContain(
      'ยาวเกินขีดจำกัด',
    );
    expect(jobWarning({ state: 'failed', error_code: 'transcript_unavailable' } as Job)).toContain(
      'ไม่พบบทถอดเสียง',
    );
  });
  it('distinguishes provider downtime from quota limits', () => {
    expect(
      jobWarning({ state: 'failed', error_code: 'generation_provider_busy' } as Job),
    ).toContain('ไม่พร้อมให้บริการชั่วคราว');
    expect(jobWarning({ state: 'failed', error_code: 'generation_rate_limited' } as Job)).toContain(
      'มีคำขอจำนวนมาก',
    );
    expect(
      jobWarning({ state: 'queued', error_code: 'generation_provider_busy' } as Job),
    ).toBeNull();
  });
});

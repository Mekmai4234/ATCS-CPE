// Explicit test-only normalized presentation bridge. These routes/field names
// are NOT module-02's public contract and are never installed in production.
import type { EvidenceBridge } from '../src/types';
export const visualFixture: EvidenceBridge = {
  source(video) {
    if (video.video_id === 'VisualDemo1')
      return {
        kinds: ['ocr', 'visual'],
        version: 'visual-v1',
        queryable: true,
        stage: 'completed',
      };
    if (video.video_id === 'wD3NSzYtsMc')
      return {
        kinds: ['transcript'],
        version: 'text-v1',
        queryable: true,
        stage: 'waiting_ai',
        limitation: 'ภาพเสริมยังรอคิว แต่ถามจากบทถอดเสียงได้',
      };
    return undefined;
  },
  citation(citation) {
    if (!citation.citation_id.startsWith('frame-')) return undefined;
    return {
      kind: citation.citation_id.includes('ocr') ? 'ocr' : 'visual',
      version: 'visual-v1',
      frame: {
        frameId: citation.citation_id,
        videoId: citation.video_id,
        generation: 1,
        evidenceVersion: 'visual-v1',
        timeSeconds: 14,
      },
      ocrText: '<img src=x onerror=alert(1)> ข้อความที่ OCR อ่านได้',
      description: '[FIXTURE] ตัวอย่างภาพ ไม่ใช่การวิเคราะห์วิดีโอจริง',
    };
  },
  coverage(result) {
    return result.citations?.some((value) => value.citation_id.startsWith('frame-'))
      ? { inspectedFrames: 12, sampledAt: [14, 30, 60], wholeVideoReviewed: false }
      : undefined;
  },
  job(job) {
    return job.stage === 'fixture_quota'
      ? { stage: 'quota_paused', retryAt: '2026-10-25T06:00:00Z' }
      : undefined;
  },
  asset(frame, signal, read) {
    return read(`/api/test-only/frames/${encodeURIComponent(frame.frameId)}`, signal);
  },
};

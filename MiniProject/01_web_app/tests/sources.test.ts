import { describe, expect, it } from 'vitest';
import { reconcileSources, snapshotSources, sourceKey } from '../src/sources';
import type { Artifact, SourceSnapshot, TaskResult, Video } from '../src/types';

const videos = ['dQw4w9WgXcQ', 'wD3NSzYtsMc'].map((video_id) => ({
  video_id,
  generation: 1,
  indexed_version: 'v1',
  status: 'ready',
  channel_id: 'c1',
  published_at: '2026-10-01',
})) as Video[];
const sources: SourceSnapshot[] = videos.map(({ video_id, generation, indexed_version }) => ({
  video_id,
  generation,
  indexed_version,
}));
const result: TaskResult = {
  answer: 'Answer',
  sources_available: true,
  citations: videos.map((v, i) => ({
    citation_id: `c${i}`,
    chunk_id: `chunk${i}`,
    video_id: v.video_id,
    title: 'Video',
    start_seconds: 1,
    end_seconds: 2,
    url: '',
  })),
};
const flags = (value: TaskResult) => value.citations?.map((c) => c.source_available);
describe('historical source availability', () => {
  it('allows fresh authorized answers after shared-source reattachment without reviving old membership evidence', () => {
    const scope = {
      video_ids: videos.map((video) => video.video_id),
      channel_ids: [],
      date_from: null,
      date_to: null,
    };
    const old = snapshotSources(videos, scope, new Map());
    const fresh = snapshotSources(videos, scope, new Map([[videos[0].video_id, 1]]));
    const retired = new Set([sourceKey(old[0])]);
    expect(flags(reconcileSources(result, old, { videos, retired }))).toEqual([false, true]);
    expect(flags(reconcileSources(result, fresh, { videos, retired }))).toEqual([true, true]);
  });
  it('invalidates only the deleted video, including nested learning artifacts', () => {
    const artifact = {
      type: 'flashcards',
      content: { cards: [] },
      citations: result.citations!,
      sources_available: true,
      coverage: {
        expected_videos: 2,
        processed_videos: 2,
        expected_chunks: 2,
        processed_chunks: 2,
        complete: true,
        notes: [],
      },
    } as Artifact;
    const updated = reconcileSources({ ...result, artifacts: [artifact] }, sources, {
      unavailableVideoIds: new Set([videos[0].video_id]),
    });
    expect(flags(updated)).toEqual([false, true]);
    expect(updated.sources_available).toBe(false);
    expect(updated.artifacts?.[0].citations.map((c) => c.source_available)).toEqual([false, true]);
    expect(result.citations?.[0].source_available).toBeUndefined();
  });
  it.each([
    { generation: 2 },
    { indexed_version: 'v2' },
    { indexed_version: null },
    { status: 'indexing' },
  ])('rejects changed source identity %j', (patch) => {
    expect(
      flags(
        reconcileSources(result, sources, {
          videos: [{ ...videos[0], ...patch } as Video, videos[1]],
        }),
      ),
    ).toEqual([false, true]);
  });
  it('never revives invalidated evidence even after the original metadata reappears', () => {
    const stale = reconcileSources(result, sources, {
      unavailableVideoIds: new Set([videos[0].video_id]),
    });
    expect(flags(reconcileSources(stale, sources, { videos, serverAvailable: true }))).toEqual([
      false,
      true,
    ]);
  });
  it('retires the old generation while allowing a new result for the same video ID', () => {
    const retired = new Set([sourceKey(sources[0])]);
    const replacement = { ...videos[0], generation: 2, indexed_version: 'v2' };
    const newSources = [{ ...sources[0], generation: 2, indexed_version: 'v2' }, sources[1]];
    expect(
      flags(reconcileSources(result, sources, { retired, videos: [replacement, videos[1]] })),
    ).toEqual([false, true]);
    expect(
      flags(reconcileSources(result, newSources, { retired, videos: [replacement, videos[1]] })),
    ).toEqual([true, true]);
  });
  it('does not treat unloaded pagination as deletion', () => {
    expect(
      flags(reconcileSources(result, sources, { videos: [videos[1]], completeInventory: false })),
    ).toEqual([true, true]);
    expect(
      flags(reconcileSources(result, sources, { videos: [videos[1]], completeInventory: true })),
    ).toEqual([false, true]);
  });
  it('uses server failure conservatively while preserving a proven unchanged source', () => {
    expect(
      flags(reconcileSources(result, sources, { videos: [videos[1]], serverAvailable: false })),
    ).toEqual([false, true]);
    expect(flags(reconcileSources(result, [], { serverAvailable: false }))).toEqual([false, false]);
  });
  it('never overrides an unavailable initial server result', () => {
    expect(
      flags(reconcileSources({ ...result, sources_available: false }, sources, { videos })),
    ).toEqual([false, false]);
  });
  it('captures only the resolved scope and copies identity before async submission', () => {
    const scoped = snapshotSources(videos, {
      video_ids: videos.map((v) => v.video_id),
      channel_ids: ['c1'],
      date_from: '2026-10-01',
      date_to: '2026-10-01',
    });
    expect(scoped).toEqual(sources);
    expect(scoped[0]).not.toBe(videos[0]);
    expect(
      snapshotSources(videos, {
        video_ids: [videos[0].video_id],
        channel_ids: ['other'],
        date_from: null,
        date_to: null,
      }),
    ).toEqual([]);
  });
});

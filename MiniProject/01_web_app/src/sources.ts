import type { Citation, Scope, SourceSnapshot, TaskResult, Video } from './types';

export const sourceKey = (source: SourceSnapshot) =>
  JSON.stringify([
    source.video_id,
    source.generation ?? null,
    source.indexed_version ?? null,
    source.accessRevision ?? null,
  ]);

export function snapshotSources(
  videos: Video[],
  scope: Scope,
  revisions?: ReadonlyMap<string, number>,
): SourceSnapshot[] {
  return videos
    .filter(
      (video) =>
        scope.video_ids.includes(video.video_id) &&
        (!scope.channel_ids.length ||
          (!!video.channel_id && scope.channel_ids.includes(video.channel_id))) &&
        (!scope.date_from ||
          (!!video.published_at && video.published_at.slice(0, 10) >= scope.date_from)) &&
        (!scope.date_to ||
          (!!video.published_at && video.published_at.slice(0, 10) <= scope.date_to)),
    )
    .map(({ video_id, generation, indexed_version }) => ({
      video_id,
      generation,
      indexed_version,
      ...(revisions ? { accessRevision: revisions.get(video_id) || 0 } : {}),
    }));
}

interface SourceCheck {
  videos?: Video[];
  completeInventory?: boolean;
  unavailableVideoIds?: ReadonlySet<string>;
  retired?: ReadonlySet<string>;
  serverAvailable?: boolean;
}

// Unavailability is monotonic for a historical result. Never re-enable a citation
// just because its video ID reappears; generation AND indexed version identify it.
export function reconcileSources(
  result: TaskResult,
  sources: SourceSnapshot[],
  check: SourceCheck = {},
): TaskResult {
  const verify = (citation: Citation, fallback: boolean): Citation => {
    let available = citation.source_available ?? fallback;
    const source = sources.find((s) => s.video_id === citation.video_id);
    const current = check.videos?.find((video) => video.video_id === citation.video_id);
    const versionKnown =
      source?.generation !== undefined &&
      !!source.indexed_version &&
      current?.generation !== undefined &&
      !!current.indexed_version;
    const sameVersion =
      versionKnown &&
      source.generation === current.generation &&
      source.indexed_version === current.indexed_version &&
      current.status === 'ready';
    if (
      check.unavailableVideoIds?.has(citation.video_id) ||
      (source && check.retired?.has(sourceKey(source)))
    )
      available = false;
    if (
      current &&
      (current.status !== 'ready' ||
        (source?.generation !== undefined &&
          current.generation !== undefined &&
          source.generation !== current.generation) ||
        (source?.indexed_version &&
          current.indexed_version !== undefined &&
          source.indexed_version !== current.indexed_version))
    )
      available = false;
    if (check.completeInventory && !current) available = false;
    // The server flag covers the whole resolved scope. A proven unchanged source
    // can remain linked when another source invalidated that aggregate flag.
    if (check.serverAvailable === false && !sameVersion) available = false;
    return { ...citation, source_available: available };
  };
  const citations = result.citations?.map((c) => verify(c, result.sources_available !== false));
  const artifacts = result.artifacts?.map((artifact) => {
    const refs = artifact.citations.map((c) => verify(c, artifact.sources_available !== false));
    return {
      ...artifact,
      citations: refs,
      sources_available:
        artifact.sources_available !== false &&
        check.serverAvailable !== false &&
        refs.every((c) => c.source_available !== false),
    };
  });
  return {
    ...result,
    citations,
    artifacts,
    sources_available:
      result.sources_available !== false &&
      check.serverAvailable !== false &&
      (citations || []).every((c) => c.source_available !== false) &&
      (artifacts || []).every((artifact) => artifact.sources_available !== false),
  };
}

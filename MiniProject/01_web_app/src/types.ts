export type JobState =
  'queued' | 'running' | 'paused' | 'completed' | 'partial' | 'failed' | 'cancelled';
export type VideoStatus =
  | 'queued'
  | 'fetching_transcript'
  | 'indexing'
  | 'ready'
  | 'no_transcript'
  | 'failed'
  | 'deleting'
  | 'deleted';
export interface Video {
  presentation?: SourcePresentation;
  generation?: number;
  indexed_version?: string | null;
  video_id: string;
  title: string | null;
  channel_id: string | null;
  channel_title: string | null;
  thumbnail_url: string | null;
  published_at: string | null;
  canonical_url: string;
  status: VideoStatus;
}
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  mode: string;
}
export interface Scope {
  video_ids: string[];
  channel_ids: string[];
  date_from: string | null;
  date_to: string | null;
}
export interface ImportItem {
  input_index: number;
  outcome: 'accepted' | 'existing' | 'rejected';
  video_id: string | null;
  job_id: string | null;
  error_code: string | null;
}
export interface Citation {
  presentation?: CitationPresentation;
  citation_id: string;
  chunk_id: string;
  video_id: string;
  title: string;
  start_seconds: number;
  end_seconds: number;
  url: string;
  source_available?: boolean;
}
export interface Coverage {
  expected_videos: number;
  processed_videos: number;
  expected_chunks: number | null;
  processed_chunks: number | null;
  complete: boolean;
  notes: string[];
}
export interface Answer {
  job_id?: string;
  status: 'answered' | 'insufficient_evidence';
  answer: string;
  citations: Citation[];
  coverage: Coverage;
  conversation_id?: string;
  sources_available?: boolean;
  provider_metadata?: { provider: string; requested_model: string; returned_model?: string | null };
  mode?: string;
}
export interface SourceSnapshot {
  evidenceVersion?: string;
  accessRevision?: number; // Client-only library membership epoch, never an authorization claim.
  video_id: string;
  generation?: number;
  indexed_version?: string | null;
}
export interface Artifact {
  artifact_id?: string;
  type: 'quiz' | 'flashcards' | 'study_plan';
  content: {
    questions?: { question: string; answer: string; explanation: string; citations: string[] }[];
    cards?: { front: string; back: string; citations: string[] }[];
    days?: { day: number; topic: string; citations: string[] }[];
  };
  citations: Citation[];
  coverage: Coverage;
  sources_available?: boolean;
}
export interface TaskResult extends Partial<Answer> {
  visualCoverage?: VisualCoverage;
  content?: string;
  artifacts?: Artifact[];
  artifact_ids?: string[];
}
export interface Job {
  wait?: {
    reason?: string;
    time_source?: 'provider' | 'estimate';
    retry_at?: string;
    estimated_retry_at?: string;
    scheduled_retry_at?: string;
  };
  presentation?: JobPresentation;
  job_id: string;
  kind: string;
  state: JobState;
  stage: string;
  video_id: string | null;
  conversation_id?: string | null;
  error_code: string | null;
  retryable: boolean;
  cancel_requested: boolean;
  attempt_count: number;
  max_attempts: number;
  result: TaskResult | null;
  sources_available?: boolean;
  mode: string;
}
// Internal view models, NOT an agreed module-02 wire schema. Only an explicitly
// installed EvidenceBridge may populate these; legacy HTTP responses stay legacy.
export type EvidenceKind = 'transcript' | 'ocr' | 'visual';
export type EnrichmentStage =
  'preparing_frames' | 'reading_text' | 'waiting_ai' | 'quota_paused' | 'partial' | 'completed';
export interface SourcePresentation {
  kinds: EvidenceKind[];
  version: string;
  queryable: boolean;
  stage: EnrichmentStage;
  limitation?: string;
}
export interface FrameReference {
  videoId: string;
  generation: number;
  evidenceVersion: string;
  frameId: string;
  timeSeconds: number;
}
export interface CitationPresentation {
  kind: EvidenceKind;
  version: string;
  frame?: FrameReference;
  ocrText?: string;
  description?: string;
}
export interface VisualCoverage {
  inspectedFrames: number;
  sampledAt: number[];
  wholeVideoReviewed: false;
}
export interface JobPresentation {
  stage: EnrichmentStage;
  retryAt?: string;
}
export interface EvidenceBridge {
  source(video: Video): SourcePresentation | undefined;
  citation(citation: Citation): CitationPresentation | undefined;
  coverage(result: TaskResult): VisualCoverage | undefined;
  job(job: Job): JobPresentation | undefined;
  asset(
    frame: FrameReference,
    signal: AbortSignal,
    read: (path: string, signal: AbortSignal) => Promise<Blob>,
  ): Promise<Blob>;
}
export interface Accepted {
  job_id: string;
  state: JobState;
  run_id?: string;
}
export interface ProgressEvent {
  event_id: number;
  step: number;
  tool_name: string;
  state: string;
  summary: string;
  timestamp: string;
}
export interface ConversationPage {
  conversation_id: string;
  total: number;
  limit: number;
  offset: number;
  messages: {
    message_id: string;
    job_id: string;
    role: string;
    content: string;
    citations: Citation[];
    scope: { video_id: string; generation?: number; transcript_version?: string }[];
    state: JobState;
  }[];
}
export type TaskType = 'chat' | 'summary' | 'compare' | 'research' | Artifact['type'];

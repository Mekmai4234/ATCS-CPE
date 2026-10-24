export type JobState = 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled';
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
  content?: string;
  artifacts?: Artifact[];
  artifact_ids?: string[];
}
export interface Job {
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

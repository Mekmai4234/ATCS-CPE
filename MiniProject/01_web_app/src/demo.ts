import type { Answer, Artifact, Job, ProgressEvent, Scope, SourceSnapshot, Video } from './types';
import type { Transport } from './api';
import { videoIdFromUrl, terminal } from './domain';

// Explicit browser-only sandbox. Uses synthetic lessons unrelated to the video URLs.
export function demoTransport(): Transport {
  const videos = new Map<string, Video>();
  const generations = new Map<string, number>();
  const jobSources = new Map<string, SourceSnapshot[]>();
  const artifactSources = new Map<string, SourceSnapshot[]>();
  const sourcesAvailable = (sources: SourceSnapshot[]) =>
    sources.every((source) => {
      const video = videos.get(source.video_id);
      return (
        video?.status === 'ready' &&
        video.generation === source.generation &&
        video.indexed_version === source.indexed_version
      );
    });
  const jobs = new Map<string, Job & { ticks: number; payload?: Record<string, unknown> }>();
  const artifacts = new Map<string, Artifact>();
  const keys = new Map<string, { input: string; job: string }>();
  const makeVideo = (id: string, title: string, status: Video['status'] = 'ready'): Video => {
    const generation = (generations.get(id) || 0) + 1;
    generations.set(id, generation);
    return {
      generation,
      indexed_version: `demo-${id}-${generation}`,
      video_id: id,
      title: `[ตัวอย่าง] ${title}`,
      status,
      channel_id: 'demo-channel',
      channel_title: 'Knowledge Studio · ข้อมูลจำลอง',
      thumbnail_url: null,
      published_at: '2026-10-01',
      canonical_url: `https://www.youtube.com/watch?v=${id}`,
    };
  };
  videos.set('dQw4w9WgXcQ', makeVideo('dQw4w9WgXcQ', 'เริ่มต้นเข้าใจ RAG และการค้นคืนความรู้'));
  videos.set('wD3NSzYtsMc', makeVideo('wD3NSzYtsMc', 'จากข้อมูลสู่คำตอบที่ตรวจสอบได้'));
  function answer(payload: Record<string, unknown>): Answer {
    const scope = payload.scope as Scope;
    const ids = scope.video_ids;
    const insufficient = /ไม่มีข้อมูล|นอกเรื่อง|unknown/i.test(String(payload.question));
    return {
      status: insufficient ? 'insufficient_evidence' : 'answered',
      answer: insufficient
        ? 'ข้อมูลตัวอย่างไม่มีหลักฐานเพียงพอสำหรับคำถามนี้ ลองเลือกคลิปเพิ่มเติมหรือปรับคำถาม'
        : '[คำตอบจำลอง] RAG ค้นคืนข้อความที่เกี่ยวข้องจากฐานความรู้ แล้วใช้ข้อความนั้นประกอบการสร้างคำตอบ ทำให้ย้อนกลับไปตรวจแหล่งอ้างอิงได้\n\nนี่เป็นข้อมูลสังเคราะห์สำหรับทดลองหน้าเว็บ ไม่ใช่เนื้อหาจริงจากคลิป',
      citations: insufficient
        ? []
        : ids.map((id, i) => ({
            citation_id: `source-${i + 1}`,
            chunk_id: `demo-${id}`,
            video_id: id,
            title: videos.get(id)?.title || 'คลิปตัวอย่าง',
            start_seconds: 14 + i * 20,
            end_seconds: 28 + i * 20,
            url: '',
          })),
      coverage: {
        expected_videos: ids.length,
        processed_videos: insufficient ? 0 : ids.length,
        expected_chunks: ids.length,
        processed_chunks: insufficient ? 0 : ids.length,
        complete: !insufficient,
        notes: insufficient ? ['ไม่พบหลักฐานในชุดข้อมูลจำลอง'] : [],
      },
      conversation_id: String(payload.conversation_id || crypto.randomUUID()),
      sources_available: true,
      mode: 'fixture',
      provider_metadata: { provider: 'fixture', requested_model: 'demo', returned_model: null },
    };
  }
  const createJob = (
    kind: string,
    payload?: Record<string, unknown>,
    videoId: string | null = null,
  ): Job & { ticks: number; payload?: Record<string, unknown> } => {
    const job: Job & { ticks: number; payload?: Record<string, unknown> } = {
      job_id: crypto.randomUUID(),
      kind,
      state: 'queued',
      stage: 'queued',
      video_id: videoId,
      error_code: null,
      retryable: false,
      cancel_requested: false,
      attempt_count: 0,
      max_attempts: 3,
      result: null,
      mode: 'fixture',
      ticks: 0,
      payload,
    };
    jobs.set(job.job_id, job);
    const scope = payload?.scope as Scope | undefined;
    if (scope)
      jobSources.set(
        job.job_id,
        scope.video_ids.map((id) => {
          const { video_id, generation, indexed_version } = videos.get(id)!;
          return { video_id, generation, indexed_version };
        }),
      );
    return job;
  };
  const advance = (job: ReturnType<typeof jobs.get>) => {
    if (!job || terminal(job.state)) return;
    job.ticks++;
    job.state = 'running';
    job.stage = job.kind === 'import' ? 'indexing' : 'running';
    job.attempt_count = 1;
    if (job.video_id && job.kind === 'import') videos.get(job.video_id)!.status = 'indexing';
    if (job.ticks < 2) return;
    job.state = 'completed';
    job.stage = 'completed';
    if (job.kind === 'import') {
      const missing = job.video_id === 'NoCaption01';
      videos.get(job.video_id!)!.status = missing ? 'no_transcript' : 'ready';
      job.stage = missing ? 'no_transcript' : 'ready';
      job.error_code = missing ? 'no_transcript' : null;
    } else if (job.kind === 'delete') videos.delete(job.video_id!);
    else {
      const result = answer(job.payload!);
      result.job_id = job.job_id;
      if (job.kind === 'artifact') {
        const id = crypto.randomUUID();
        const type = job.payload!.type as Artifact['type'];
        const refs = result.citations.map((c) => c.citation_id);
        const content =
          type === 'quiz'
            ? {
                questions: [
                  {
                    question: 'RAG ช่วยอะไร?',
                    answer: 'ค้นหลักฐานก่อนสร้างคำตอบ',
                    explanation: 'คำตอบจำลองจากบทเรียนสังเคราะห์',
                    citations: refs,
                  },
                ],
              }
            : type === 'flashcards'
              ? {
                  cards: [
                    {
                      front: 'RAG คืออะไร?',
                      back: 'การสร้างคำตอบร่วมกับการค้นคืนข้อมูล',
                      citations: refs,
                    },
                  ],
                }
              : {
                  days: Array.from({ length: Number(job.payload!.days) || 7 }, (_, i) => ({
                    day: i + 1,
                    topic: `บทเรียนจำลองวันที่ ${i + 1}: ศึกษา RAG`,
                    citations: refs,
                  })),
                };
        artifacts.set(id, {
          artifact_id: id,
          type,
          content,
          citations: result.citations,
          coverage: result.coverage,
        });
        artifactSources.set(id, jobSources.get(job.job_id) || []);
        job.result = { artifact_ids: [id] };
      } else if (job.kind === 'research') {
        job.state = 'partial';
        job.result = {
          content:
            '[ผลค้นคว้าจำลอง] พบหลักการค้นคืนและการตรวจหลักฐาน แต่ยังศึกษาได้ไม่ครบทุกหัวข้อ',
          citations: result.citations,
          coverage: {
            ...result.coverage,
            complete: false,
            processed_chunks: 0,
            notes: ['ตัวอย่างผลบางส่วนเมื่อหมดงบค้นคว้า'],
          },
        };
      } else job.result = result;
    }
  };
  const json = (data: unknown, status = 200) =>
    new Response(JSON.stringify(data), {
      status,
      headers: { 'Content-Type': 'application/json', 'X-Adapter-Mode': 'fixture' },
    });
  const error = (message: string, code: string, status = 422) =>
    json({ error: { message, code, retryable: false, request_id: 'demo' } }, status);
  return async (input, init) => {
    init?.signal?.throwIfAborted();
    const url = new URL(String(input), 'http://demo.test');
    const path = url.pathname;
    const method = init?.method || 'GET';
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
    if (path === '/api/videos' && method === 'GET') {
      const all = [...videos.values()].filter((v) => v.status !== 'deleting');
      const offset = Number(url.searchParams.get('offset')) || 0;
      return json({
        items: all.slice(offset, offset + 50),
        total: all.length,
        offset,
        limit: 50,
        mode: 'fixture',
      });
    }
    if (path === '/api/videos/import') {
      const results = (body.urls as string[]).map((value, input_index) => {
        const id = videoIdFromUrl(value);
        if (!id)
          return {
            input_index,
            outcome: 'rejected',
            video_id: null,
            job_id: null,
            error_code: 'invalid_youtube_url',
          };
        const old = [...jobs.values()].find((j) => j.kind === 'import' && j.video_id === id);
        if (videos.has(id))
          return {
            input_index,
            outcome: 'existing',
            video_id: id,
            job_id: old?.job_id || null,
            error_code: null,
          };
        videos.set(id, makeVideo(id, `คลิปที่นำเข้า ${id}`, 'queued'));
        const job = createJob('import', undefined, id);
        return {
          input_index,
          outcome: 'accepted',
          video_id: id,
          job_id: job.job_id,
          error_code: null,
        };
      });
      return json({ jobs: results, mode: 'fixture' }, 202);
    }
    const jobMatch = path.match(/^\/api\/jobs\/([^/]+)(?:\/(cancel|retry))?$/);
    if (jobMatch) {
      const job = jobs.get(jobMatch[1]);
      if (!job) return error('ไม่พบงาน', 'job_not_found', 404);
      if (jobMatch[2] === 'cancel') {
        if (!terminal(job.state)) {
          job.state = 'cancelled';
          job.stage = 'cancelled';
        }
      } else if (jobMatch[2] === 'retry')
        return error('งานนี้ไม่รองรับการลองใหม่', 'not_retryable', 409);
      else advance(job);
      return json({
        ...job,
        ...(jobSources.has(job.job_id)
          ? { sources_available: sourcesAvailable(jobSources.get(job.job_id)!) }
          : {}),
      });
    }
    if (path.startsWith('/api/videos/') && method === 'DELETE') {
      const id = path.split('/')[3];
      if (!videos.has(id)) return error('ไม่พบคลิป', 'not_found', 404);
      videos.get(id)!.status = 'deleting';
      return json(createJob('delete', undefined, id), 202);
    }
    if (path.startsWith('/api/research/') && method === 'GET') {
      const job = jobs.get(path.split('/')[3]);
      if (!job) return error('ไม่พบงาน', 'not_found', 404);
      const events: ProgressEvent[] = [
        {
          event_id: 1,
          step: 1,
          tool_name: 'search_evidence',
          state: 'completed',
          summary: 'ค้นหลักฐานในชุดข้อมูลจำลอง',
          timestamp: new Date().toISOString(),
        },
      ];
      return json({
        ...job,
        events: Number(url.searchParams.get('after_event_id')) >= 1 ? [] : events,
      });
    }
    if (path.startsWith('/api/learning-artifacts/') && method === 'GET') {
      const artifact = artifacts.get(path.split('/')[3]);
      return artifact
        ? json({
            ...artifact,
            sources_available: sourcesAvailable(artifactSources.get(artifact.artifact_id!) || []),
          })
        : error('ไม่พบสื่อเรียนรู้', 'not_found', 404);
    }
    if (path === '/api/conversations' && method === 'GET') {
      const grouped = new Map<string, import('./types').ConversationSummary>();
      for (const job of jobs.values()) {
        const id = job.kind === 'chat' ? job.result?.conversation_id : null;
        if (!id) continue;
        const previous = grouped.get(id);
        grouped.set(id, {
          conversation_id: id,
          title:
            previous?.title || String(job.payload?.question || 'บทสนทนาตัวอย่าง').slice(0, 160),
          created_at: previous?.created_at || '2026-10-01T00:00:00Z',
          updated_at: '2026-10-01T00:00:00Z',
          message_count: (previous?.message_count || 0) + 2,
          video_ids: (job.payload?.scope as Scope)?.video_ids || [],
        });
      }
      const items = [...grouped.values()]
        .reverse()
        .filter((item) => item.title.includes(url.searchParams.get('q') || ''));
      const offset = Number(url.searchParams.get('offset') || 0);
      return json({
        items: items.slice(offset, offset + 20),
        total: items.length,
        offset,
        limit: 20,
      });
    }
    if (path.startsWith('/api/conversations/') && method === 'GET') {
      const id = decodeURIComponent(path.split('/')[3]);
      const messages = [...jobs.values()]
        .filter((job) => job.kind === 'chat' && job.result?.conversation_id === id)
        .flatMap((job) => {
          const scope = (jobSources.get(job.job_id) || []).map((source) => ({
            video_id: source.video_id,
            generation: source.generation,
            transcript_version: source.indexed_version,
          }));
          const available = sourcesAvailable(jobSources.get(job.job_id) || []);
          const base = { job_id: job.job_id, scope, state: job.state };
          return [
            {
              ...base,
              message_id: `${job.job_id}-q`,
              role: 'user',
              content: String(job.payload?.question || ''),
              citations: [],
            },
            {
              ...base,
              message_id: `${job.job_id}-a`,
              role: 'assistant',
              content: job.result?.answer || '',
              citations: (job.result?.citations || []).map((citation) => ({
                ...citation,
                source_available: available,
              })),
            },
          ];
        });
      const offset = Number(url.searchParams.get('offset') || 0);
      return json({
        conversation_id: id,
        scope:
          [...jobs.values()].filter((job) => job.result?.conversation_id === id).at(-1)?.payload
            ?.scope || null,
        messages: messages.slice(offset, offset + 50),
        total: messages.length,
        limit: 50,
        offset,
      });
    }
    if (['/api/chat', '/api/analysis', '/api/research', '/api/learning-artifacts'].includes(path)) {
      const scope = body.scope as Scope;
      if (
        !scope?.video_ids?.length ||
        scope.video_ids.some((id) => videos.get(id)?.status !== 'ready')
      )
        return error('เลือกคลิปที่พร้อมก่อน', 'video_not_ready', 409);
      const key = new Headers(init?.headers).get('Idempotency-Key') || crypto.randomUUID();
      const inputText = JSON.stringify(body);
      const keyId = `${path}:${key}`;
      const existing = keys.get(keyId);
      if (existing) {
        if (existing.input !== inputText)
          return error('key เดิมมีข้อมูลต่างกัน', 'idempotency_conflict', 409);
        const job = jobs.get(existing.job)!;
        return path === '/api/chat' && job.result ? json(job.result) : json(job, 202);
      }
      const kind =
        path === '/api/chat'
          ? 'chat'
          : path === '/api/analysis'
            ? 'analysis'
            : path === '/api/research'
              ? 'research'
              : 'artifact';
      const job = createJob(kind, body);
      keys.set(keyId, { input: inputText, job: job.job_id });
      if (kind === 'chat' && !/รอผล/.test(String(body.question))) {
        job.state = 'completed';
        job.stage = 'completed';
        job.result = answer(body);
        job.result.job_id = job.job_id;
        return json(job.result);
      }
      return json(
        {
          job_id: job.job_id,
          state: job.state,
          ...(kind === 'research' ? { run_id: job.job_id } : {}),
        },
        202,
      );
    }
    return error('ไม่มี endpoint นี้ในโหมดตัวอย่าง', 'not_found', 404);
  };
}

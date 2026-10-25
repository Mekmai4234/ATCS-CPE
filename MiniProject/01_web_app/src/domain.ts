import type { Citation, Job, Scope, Video } from './types';
export const evidenceLabels = {
  transcript: 'บทถอดเสียง',
  ocr: 'ข้อความบนภาพ',
  visual: 'ภาพวิเคราะห์แล้ว',
};
export const enrichmentLabels = {
  preparing_frames: 'เตรียมภาพ',
  reading_text: 'อ่านข้อความ',
  waiting_ai: 'รอคิว AI',
  quota_paused: 'พักเพราะข้อจำกัดการใช้งาน',
  partial: 'พร้อมบางส่วน',
  completed: 'เสร็จแล้ว',
};
export const videoQueryable = (video: Video) =>
  !['deleted', 'deleting'].includes(video.status) &&
  (video.status === 'ready' ||
    !!(video.presentation?.queryable && video.presentation.kinds.length));
export function jobStatus(job: Job) {
  const extra = job.presentation;
  const provider =
    job.error_code === 'generation_rate_limited'
      ? 'Gemini จำกัดการใช้งาน (429); ยังไม่ทราบว่าโควตารายวันหมดหรือไม่'
      : job.error_code === 'generation_provider_busy'
        ? 'Gemini ไม่พร้อมให้บริการชั่วคราว (503)'
        : '';
  const stage = extra
    ? enrichmentLabels[extra.stage]
    : statusLabels[job.stage] || statusLabels[job.state] || job.state;
  const when =
    extra?.retryAt && Number.isFinite(Date.parse(extra.retryAt))
      ? ` · Backend ระบุให้ลองอีกครั้ง ${new Date(extra.retryAt).toLocaleString('th-TH')}`
      : '';
  return `${stage}${provider ? ` · ${provider}` : ''}${when}`;
}

export const terminal = (state: string) =>
  ['completed', 'partial', 'failed', 'cancelled'].includes(state);
export const statusLabels: Record<string, string> = {
  queued: 'รอคิว',
  running: 'กำลังทำงาน',
  fetching_transcript: 'กำลังดึงบทถอดเสียง',
  indexing: 'กำลังสร้างฐานความรู้',
  ready: 'พร้อมใช้งาน',
  no_transcript: 'ไม่มีบทถอดเสียง',
  completed: 'เสร็จแล้ว',
  partial: 'ได้ผลบางส่วน',
  failed: 'ไม่สำเร็จ',
  cancelled: 'ยกเลิกแล้ว',
  deleting: 'กำลังลบ',
  deleted: 'ลบแล้ว',
};
export function videoIdFromUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || url.username || url.password || url.port) return null;
    const id =
      url.hostname === 'youtu.be' && /^\/[\w-]{11}\/?$/.test(url.pathname)
        ? url.pathname.split('/')[1]
        : ['youtube.com', 'www.youtube.com', 'm.youtube.com'].includes(url.hostname) &&
            url.pathname === '/watch'
          ? url.searchParams.get('v')
          : null;
    return id && /^[\w-]{11}$/.test(id) ? id : null;
  } catch {
    return null;
  }
}
export function citationUrl(citation: Citation): string | null {
  if (
    !/^[\w-]{11}$/.test(citation.video_id) ||
    !Number.isFinite(citation.start_seconds) ||
    !Number.isFinite(citation.end_seconds) ||
    citation.start_seconds < 0 ||
    citation.end_seconds <= citation.start_seconds ||
    citation.source_available === false
  )
    return null;
  return `https://www.youtube.com/watch?v=${citation.video_id}&t=${Math.floor(citation.start_seconds)}s`;
}
export function timestamp(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
}
export function buildScope(
  ids: string[],
  videos: Video[],
  channel: string,
  from: string,
  to: string,
): Scope {
  if (!ids.length) throw new Error('เลือกคลิปที่พร้อมใช้งานอย่างน้อย 1 คลิป');
  if (ids.length > 100) throw new Error('เลือกแหล่งข้อมูลได้สูงสุด 100 คลิป');
  if (from && to && from > to) throw new Error('วันเริ่มต้นต้องไม่อยู่หลังวันสิ้นสุด');
  const selected = ids.map((id) => videos.find((video) => video.video_id === id));
  if (selected.some((video) => !video || !videoQueryable(video)))
    throw new Error('คลิปที่เลือกยังไม่พร้อมใช้งาน กรุณาตรวจสอบอีกครั้ง');
  const eligible = selected.filter(
    (video) =>
      video &&
      (!channel || video.channel_id === channel) &&
      (!from || (!!video.published_at && video.published_at.slice(0, 10) >= from)) &&
      (!to || (!!video.published_at && video.published_at.slice(0, 10) <= to)),
  );
  if (!eligible.length)
    throw new Error('ไม่มีคลิปที่เลือกตรงกับตัวกรอง กรุณาปรับตัวกรองหรือเลือกคลิปใหม่');
  return {
    video_ids: [...new Set(ids)],
    channel_ids: channel ? [channel] : [],
    date_from: from || null,
    date_to: to || null,
  };
}
export function jobWarning(job: Job): string | null {
  if (job.state === 'failed' && job.error_code === 'generation_provider_busy')
    return 'Gemini ไม่พร้อมให้บริการชั่วคราว จึงยังสร้างคำตอบไม่ได้ กรุณารอสักครู่แล้วส่งคำถามอีกครั้ง';
  if (job.state === 'failed' && job.error_code === 'generation_rate_limited')
    return 'Gemini จำกัดจำนวนคำขอหรือโทเคน กรุณาตรวจสอบโควตาและส่งคำถามอีกครั้งเมื่อใช้งานได้';
  if (job.state === 'failed' && job.error_code === 'transcript_too_large')
    return 'บทถอดเสียงยาวเกินขีดจำกัดการแสดงผล กรุณาเลือกคลิปเดียวหรือถามเฉพาะช่วงที่ต้องการ';
  if (job.state === 'failed' && job.error_code === 'transcript_unavailable')
    return 'ไม่พบบทถอดเสียงต้นฉบับของคลิป กรุณาตรวจสอบการนำเข้าวิดีโอ';
  if (job.state === 'failed' && job.error_code === 'generation_output_truncated')
    return 'คำตอบยาวเกินขีดจำกัดและถูกตัด กรุณาถามให้เจาะจงขึ้นหรือขอสรุปสั้น ๆ';
  if (job.state === 'failed') return `งานไม่สำเร็จ (${job.error_code || 'task_failed'})`;
  if (job.state === 'cancelled') return 'งานถูกยกเลิกแล้ว';
  if (job.stage === 'no_transcript') return 'ไม่พบบทถอดเสียงที่ใช้งานได้';
  return null;
}

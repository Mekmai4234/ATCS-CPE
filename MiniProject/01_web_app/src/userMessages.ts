// Presentation only. API errors and durable jobs retain their diagnostic codes.
export const userMessages = {
  aiUnavailable: 'ขณะนี้ผู้ช่วย AI ยังไม่พร้อมให้บริการ กรุณาลองใหม่ภายหลัง',
  quotaWait: 'งบการใช้งานภายในระบบเต็ม งานเดิมยังถูกเก็บไว้ กรุณารอเวลาที่ระบบแจ้ง',
  providerLimited: 'ผู้ให้บริการจำกัดการใช้งานชั่วคราว กรุณาติดตามงานเดิมก่อนส่งซ้ำ',
  workerUnavailable: 'ตัวประมวลผลยังไม่พร้อม งานเดิมยังถูกเก็บไว้ กรุณารอก่อนส่งซ้ำ',
  busy: 'ขณะนี้มีคำขอจำนวนมาก กรุณารอสักครู่แล้วลองอีกครั้ง',
  unavailable: 'ระบบไม่พร้อมให้บริการชั่วคราว กรุณาลองใหม่ภายหลัง',
  failed: 'ทำรายการไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
  connection: 'เชื่อมต่อระบบไม่ได้ กรุณาลองใหม่อีกครั้ง',
  indexUnavailable: 'ข้อมูลคลิปยังไม่พร้อมสำหรับคำถามนี้ กรุณาลองรีเฟรชคลังหรือเลือกคลิปอื่น',
};

export function serviceMessage(code: string | null | undefined, status?: number): string | null {
  if (['free_tier_unverified', 'free_model_unverified', 'quota_pending'].includes(code || ''))
    return userMessages.aiUnavailable;
  if (code === 'quota_wait') return userMessages.quotaWait;
  if (['provider_rate_limited', 'generation_rate_limited'].includes(code || ''))
    return userMessages.providerLimited;
  if (code === 'worker_unavailable') return userMessages.workerUnavailable;
  if (code === 'local_unavailable')
    return 'AI ในเครื่องยังไม่พร้อม กรุณาตรวจบริการในเครื่องก่อนทำต่อ';
  if (code === 'local_timeout') return 'AI ในเครื่องใช้เวลานานเกินกำหนด งานนี้ยังไม่สำเร็จ';
  if (status === 429) return userMessages.busy;
  if (
    ['generation_provider_busy', 'provider_unavailable', 'generation_provider_error'].includes(
      code || '',
    ) ||
    status === 503
  )
    return userMessages.unavailable;
  if (code === 'moderation_confirmation_required')
    return 'กรุณาตรวจและยืนยันข้อความใหม่ก่อนส่งอีกครั้ง';
  if (code === 'moderation_blocked') return 'กรุณาปรับข้อความให้เหมาะสมก่อนส่งอีกครั้ง';
  if (code === 'invalid_video_time') return 'เวลาไม่ถูกต้อง ใช้รูปแบบ 01:20 หรือ 01:20:30';
  if (code === 'invalid_video_time_range') return 'เวลาสิ้นสุดต้องมากกว่าเวลาเริ่มต้น';
  if (code === 'video_time_out_of_bounds') return 'รองรับเวลาวิดีโอไม่เกิน 02:00:00';
  if (code === 'ambiguous_video_time') return 'ระบุเวลาเดียวหรือช่วงต่อเนื่อง เช่น 01:00 ถึง 04:00';
  if (code === 'context_budget_exceeded')
    return 'เนื้อหาที่เลือกเกินขีดจำกัด กรุณาเลือกคลิปน้อยลงหรือระบุหัวข้อ';
  if (['generation_timeout', 'task_timeout', 'agent_budget_exhausted'].includes(code || ''))
    return 'งานนี้ใช้เวลานานเกินกำหนด กรุณาลองใหม่หรือเลือกคลิปน้อยลง';
  if (code === 'invalid_model_output') return 'AI ส่งผลลัพธ์ไม่สมบูรณ์ กรุณาลองสร้างใหม่';
  if (code === 'incomplete_index') return userMessages.indexUnavailable;
  if (code === 'network_error') return userMessages.connection;
  if (status && status >= 500) return userMessages.unavailable;
  return null;
}

export function importMessage(code: string): string {
  if (['no_transcript', 'transcript_unavailable'].includes(code))
    return 'ยังไม่มีบทถอดเสียงที่ระบบเข้าถึงได้ ลองคลิปที่มีคำบรรยาย';
  if (code === 'video_unavailable')
    return 'ระบบยังเข้าถึงคลิปนี้ไม่ได้ กรุณาตรวจสอบว่าเปิดดูบน YouTube ได้';
  if (['youtube_access_blocked', 'video_restricted'].includes(code))
    return 'YouTube จำกัดการเข้าถึงคลิปจากระบบนี้ ไม่สามารถดึงข้อมูลได้ในขณะนี้';
  if (
    [
      'ingest_timeout',
      'ingest_unavailable',
      'youtube_rate_limited',
      'caption_provider_transient',
    ].includes(code)
  )
    return 'เครือข่ายหรือบริการคำบรรยายยังไม่พร้อม กรุณาติดตามงานเดิมก่อนลองใหม่';
  if (['invalid_youtube_url', 'invalid_url'].includes(code))
    return 'กรุณาใช้ลิงก์วิดีโอ YouTube แบบ https://www.youtube.com/watch?v=… หรือ https://youtu.be/…';
  if (code === 'video_deleting') return 'คลิปนี้กำลังถูกลบ กรุณารอให้เสร็จแล้วนำเข้าใหม่';
  if (code === 'source_unavailable') return 'คลิปนี้ยังนำเข้าไม่ได้ กรุณาตรวจสอบว่าลิงก์เปิดดูได้';
  return serviceMessage(code) || 'นำเข้าคลิปนี้ไม่สำเร็จ กรุณาตรวจสอบลิงก์แล้วลองใหม่';
}

// Presentation only. API errors and durable jobs retain their diagnostic codes.
export const userMessages = {
  aiUnavailable: 'ขณะนี้ผู้ช่วย AI ยังไม่พร้อมให้บริการ กรุณาลองใหม่ภายหลัง',
  busy: 'ขณะนี้มีคำขอจำนวนมาก กรุณารอสักครู่แล้วลองอีกครั้ง',
  unavailable: 'ระบบไม่พร้อมให้บริการชั่วคราว กรุณาลองใหม่ภายหลัง',
  failed: 'ทำรายการไม่สำเร็จ กรุณาลองใหม่อีกครั้ง',
  connection: 'เชื่อมต่อระบบไม่ได้ กรุณาลองใหม่อีกครั้ง',
  indexUnavailable: 'ข้อมูลคลิปยังไม่พร้อมสำหรับคำถามนี้ กรุณาลองรีเฟรชคลังหรือเลือกคลิปอื่น',
};

export function serviceMessage(code: string | null | undefined, status?: number): string | null {
  if (['free_tier_unverified', 'free_model_unverified', 'quota_pending'].includes(code || ''))
    return userMessages.aiUnavailable;
  if (
    ['generation_rate_limited', 'provider_rate_limited', 'quota_wait'].includes(code || '') ||
    status === 429
  )
    return userMessages.busy;
  if (
    ['generation_provider_busy', 'provider_unavailable', 'generation_provider_error'].includes(
      code || '',
    ) ||
    status === 503
  )
    return userMessages.unavailable;
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
  if (['invalid_youtube_url', 'invalid_url'].includes(code))
    return 'กรุณาใช้ลิงก์วิดีโอ YouTube แบบ https://www.youtube.com/watch?v=… หรือ https://youtu.be/…';
  if (code === 'video_deleting') return 'คลิปนี้กำลังถูกลบ กรุณารอให้เสร็จแล้วนำเข้าใหม่';
  if (code === 'source_unavailable') return 'คลิปนี้ยังนำเข้าไม่ได้ กรุณาตรวจสอบว่าลิงก์เปิดดูได้';
  return serviceMessage(code) || 'นำเข้าคลิปนี้ไม่สำเร็จ กรุณาตรวจสอบลิงก์แล้วลองใหม่';
}

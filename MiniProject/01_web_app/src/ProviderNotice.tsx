import type { Answer } from './types';

export default function ProviderNotice({ metadata }: { metadata?: Answer['provider_metadata'] }) {
  if (!metadata) return null;
  const providers: Record<string, string> = {
    gemini: 'Gemini',
    'gemini-video': 'Gemini · ตรวจภาพและเสียงคลิป',
    ollama: 'AI ในเครื่อง',
    'ollama-cache': 'ผลที่บันทึกไว้จาก AI ในเครื่อง (cache)',
    'gemini-cache': 'ผลที่บันทึกไว้จาก Gemini (cache)',
    'answer-cache': 'ผลที่บันทึกไว้ (cache)',
    'video-cache': 'ผลที่บันทึกไว้จากการตรวจคลิป (cache)',
    fixture: 'คำตอบสังเคราะห์ · ไม่ใช่ AI จริง',
    system: 'ข้อความจากระบบ · ไม่ใช่การวิเคราะห์คลิปด้วย AI',
    transcript: 'บทถอดเสียงที่บันทึกไว้ · ไม่ได้เรียก AI',
    none: 'ไม่มีการเรียกโมเดลในผลนี้',
  };
  const origins = metadata.provider.split(',');
  const label = origins.map((origin) => providers[origin] || 'ยังไม่ทราบผู้ให้บริการ').join(' · ');
  const cached = origins.some((origin) => origin.endsWith('-cache'));
  return (
    <p className="provider-notice">
      {label} · โมเดล: {metadata.returned_model || metadata.requested_model || 'ไม่ได้ระบุ'}
      {!cached &&
        typeof metadata.latency_ms === 'number' &&
        Number.isFinite(metadata.latency_ms) &&
        metadata.latency_ms >= 0 && (
          <> · เวลาประมวลผลที่บันทึก: {Math.round(metadata.latency_ms)} ms</>
        )}
    </p>
  );
}

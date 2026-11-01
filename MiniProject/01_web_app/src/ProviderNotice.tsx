import type { Answer } from './types';

export default function ProviderNotice({ metadata }: { metadata?: Answer['provider_metadata'] }) {
  if (!metadata) return null;
  const providers: Record<string, string> = {
    gemini: 'Gemini',
    'gemini-video': 'Gemini · ตรวจภาพและเสียงคลิป',
    ollama: 'AI ในเครื่อง',
    'answer-cache': 'ผลที่บันทึกไว้ (cache)',
    'video-cache': 'ผลที่บันทึกไว้จากการตรวจคลิป (cache)',
    fixture: 'คำตอบสังเคราะห์ · ไม่ใช่ AI จริง',
    system: 'ข้อความจากระบบ · ไม่ใช่การวิเคราะห์คลิปด้วย AI',
    transcript: 'บทถอดเสียงที่บันทึกไว้ · ไม่ได้เรียก AI',
    none: 'ไม่มีการเรียกโมเดลในผลนี้',
  };
  const label = providers[metadata.provider] || 'ยังไม่ทราบผู้ให้บริการ';
  return (
    <p className="provider-notice">
      {label} · โมเดล: {metadata.returned_model || metadata.requested_model || 'ไม่ได้ระบุ'}
      {!['answer-cache', 'video-cache'].includes(metadata.provider) &&
        typeof metadata.latency_ms === 'number' &&
        Number.isFinite(metadata.latency_ms) &&
        metadata.latency_ms >= 0 && (
          <> · เวลาประมวลผลที่บันทึก: {Math.round(metadata.latency_ms)} ms</>
        )}
    </p>
  );
}

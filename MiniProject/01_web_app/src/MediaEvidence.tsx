import { useEffect, useState } from 'react';
import type { Api } from './api';
import type { MediaEvidenceData, Video } from './types';
import { FrameEvidence, VisualCoverageNotice } from './Evidence';

function EvidenceBody({ api, video }: { api: Api; video: Video }) {
  const [data, setData] = useState<MediaEvidenceData>();
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(undefined);
    setError('');
    void api
      .mediaEvidence(video.video_id, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          if (video.generation !== undefined && value.generation !== video.generation)
            throw new Error('คลิปมีเวอร์ชันใหม่ กรุณารีเฟรชคลัง');
          setData(value);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setError('โหลดหลักฐานภาพไม่ได้ หรือไม่มีสิทธิ์เปิด');
      });
    return () => controller.abort();
  }, [api, video.video_id, video.generation, attempt]);
  if (error)
    return (
      <div role="alert">
        {error} <button onClick={() => setAttempt((n) => n + 1)}>ลองใหม่</button>
      </div>
    );
  if (!data) return <p role="status">กำลังโหลดหลักฐานภาพ…</p>;
  if (!data.evidence.length)
    return (
      <p role="status">
        {data.state === 'not_requested'
          ? 'คลิปนี้ยังไม่มีหลักฐานภาพ/OCR'
          : 'ยังไม่มีภาพที่พร้อมแสดง'}
      </p>
    );
  return (
    <div className="media-evidence-list">
      <VisualCoverageNotice
        value={{
          inspectedFrames:
            data.coverage?.frame_ids?.length ||
            new Set(data.evidence.map((item) => item.frame_id)).size,
          sampledAt: [...new Set(data.evidence.map((item) => item.timestamp_seconds))],
          wholeVideoReviewed: false,
        }}
      />
      <p>ภาพและ OCR ที่บันทึกไว้ · คำถามเกี่ยวกับภาพจะวิเคราะห์คลิปเพิ่มเมื่อพร้อมใช้งาน</p>
      {data.evidence.map((item) => (
        <FrameEvidence
          key={`${item.frame_id}-${item.kind}`}
          available
          evidence={{
            kind: item.kind,
            version: item.evidence_version,
            frame: {
              videoId: data.video_id,
              generation: data.generation,
              evidenceVersion: item.evidence_version,
              frameId: item.frame_id,
              assetId: item.asset_id,
              timeSeconds: item.timestamp_seconds,
            },
            ...(item.kind === 'ocr' ? { ocrText: item.text } : { description: item.text }),
          }}
        />
      ))}
    </div>
  );
}
export default function MediaEvidence({ api, video }: { api: Api; video: Video }) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="media-evidence-panel"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>ภาพและ OCR</summary>
      {open && <EvidenceBody api={api} video={video} />}
    </details>
  );
}

import { createContext, useContext, useEffect, useState } from 'react';
import { evidenceLabels, enrichmentLabels, timestamp } from './domain';
import type {
  CitationPresentation,
  FrameReference,
  SourcePresentation,
  Video,
  VisualCoverage,
} from './types';
export type FrameLoader = (frame: FrameReference, signal: AbortSignal) => Promise<Blob>;
export const EvidenceContext = createContext<FrameLoader | undefined>(undefined);
export function validFrame(frame?: FrameReference): frame is FrameReference {
  return (
    !!frame &&
    /^[\w-]{11}$/.test(frame.videoId) &&
    Number.isInteger(frame.generation) &&
    frame.generation > 0 &&
    typeof frame.evidenceVersion === 'string' &&
    !!frame.evidenceVersion &&
    typeof frame.frameId === 'string' &&
    !!frame.frameId &&
    Number.isFinite(frame.timeSeconds) &&
    frame.timeSeconds >= 0
  );
}
export function SourceBadges({ video }: { video: Video }) {
  const info: SourcePresentation | undefined = video.presentation;
  const kinds = info?.kinds || (video.status === 'ready' ? ['transcript' as const] : []);
  return (
    <div className="evidence-badges">
      {kinds.map((kind) => (
        <span className={`evidence-kind ${kind}`} key={kind}>
          {evidenceLabels[kind]}
        </span>
      ))}
      {info && <small>{enrichmentLabels[info.stage]}</small>}
      {info?.limitation && <p className="evidence-limitation">{info.limitation}</p>}
      {video.status === 'ready' && info && info.stage !== 'completed' && (
        <p className="evidence-limitation">ถามจากบทถอดเสียงได้แล้ว ส่วนข้อมูลภาพยังไม่ครบ</p>
      )}
    </div>
  );
}
export function FrameEvidence({
  evidence,
  available,
}: {
  evidence: CitationPresentation;
  available: boolean;
}) {
  const load = useContext(EvidenceContext);
  const [src, setSrc] = useState<string>();
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const frame = evidence.frame;
  const identity = frame
    ? `${frame.videoId}:${frame.generation}:${frame.evidenceVersion}:${frame.frameId}:${frame.timeSeconds}`
    : '';
  useEffect(() => {
    setSrc(undefined);
    setError('');
    if (!available || !validFrame(frame)) return;
    if (!load) {
      setError('ยังรอ API ภาพที่ตรวจสิทธิ์');
      return;
    }
    const controller = new AbortController();
    let active = true;
    let url: string | undefined;
    void load(frame, controller.signal)
      .then((blob) => {
        if (!active) return;
        url = URL.createObjectURL(blob);
        setSrc(url);
      })
      .catch((error) => {
        if (active && !controller.signal.aborted)
          setError(error instanceof Error ? error.message : 'โหลดภาพไม่สำเร็จ');
      });
    return () => {
      active = false;
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [identity, available, load, attempt]);
  return (
    <div className="frame-evidence">
      {!available ? (
        <p>ภาพหลักฐานใช้ไม่ได้หรือถูกถอนสิทธิ์แล้ว</p>
      ) : !validFrame(frame) ? (
        <p>ข้อมูลภาพยังไม่พร้อมตรวจสอบ</p>
      ) : (
        <>
          {src && (
            <img
              src={src}
              alt={`ภาพหลักฐานจากคลิป เวลา ${timestamp(frame.timeSeconds)}`}
              onError={() => {
                URL.revokeObjectURL(src);
                setSrc(undefined);
                setError('เปิดภาพไม่ได้ คำตอบและประวัติยังคงอยู่');
              }}
            />
          )}
          {!src && !error && <p role="status">กำลังโหลดภาพที่ตรวจสิทธิ์…</p>}
          {error && (
            <div role="status">
              <p>{error}</p>
              {load && (
                <button className="text-button" onClick={() => setAttempt((value) => value + 1)}>
                  ลองโหลดภาพอีกครั้ง
                </button>
              )}
            </div>
          )}
        </>
      )}
      {evidence.ocrText !== undefined && (
        <div>
          <strong>ข้อความที่ OCR อ่านได้</strong>
          <p className="evidence-text">{evidence.ocrText}</p>
        </div>
      )}
      {evidence.description !== undefined && (
        <div>
          <strong>คำอธิบายภาพจาก AI</strong>
          <p className="evidence-text">{evidence.description}</p>
        </div>
      )}
    </div>
  );
}
export function VisualCoverageNotice({ value }: { value?: VisualCoverage }) {
  if (!value || !Number.isInteger(value.inspectedFrames) || value.inspectedFrames < 0) return null;
  const times = value.sampledAt.filter((time) => Number.isFinite(time) && time >= 0);
  return (
    <aside className="visual-coverage">
      <strong>ตรวจภาพตัวอย่าง {value.inspectedFrames} ภาพ</strong>
      <p>ตรวจเฉพาะภาพตัวอย่าง ไม่ได้หมายถึงเห็นทุกเฟรมหรือทุกช่วงของคลิป</p>
      {times.length > 0 && <p>เวลาของภาพที่ตรวจ: {times.map(timestamp).join(' · ')}</p>}
    </aside>
  );
}

import { useEffect, useRef, useState } from 'react';
export type BuddyState = 'idle' | 'thinking' | 'success' | 'error';
export default function InteractiveBuddy({
  className = '',
  state = 'idle',
  headOnly = false,
  active = true,
  decorative = false,
}: {
  className?: string;
  state?: BuddyState;
  headOnly?: boolean;
  active?: boolean;
  decorative?: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [fallback, setFallback] = useState(false);
  const [greeting, setGreeting] = useState(false);
  const wave = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(wave.current), []);
  useEffect(() => {
    const node = root.current;
    if (!node || !active || fallback || headOnly) return;
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0,
      pending = { x: 0, y: 0 };
    const draw = () => {
      frame = 0;
      node.style.setProperty('--eye-x', `${pending.x * 6}px`);
      node.style.setProperty('--eye-y', `${pending.y * 5}px`);
      node.style.setProperty('--head-tilt', `${pending.x * 5}deg`);
    };
    const reset = () => {
      pending = { x: 0, y: 0 };
      cancelAnimationFrame(frame);
      draw();
    };
    const move = (event: PointerEvent) => {
      if (document.hidden || motion.matches || event.pointerType === 'touch') return;
      const rect = node.getBoundingClientRect();
      const distance = Math.hypot(
        event.clientX - rect.x - rect.width / 2,
        event.clientY - rect.y - rect.height / 2,
      );
      if (distance > Math.max(rect.width, rect.height) * 1.6) {
        reset();
        return;
      }
      pending = {
        x: Math.max(-1, Math.min(1, (event.clientX - rect.x - rect.width / 2) / rect.width)),
        y: Math.max(-1, Math.min(1, (event.clientY - rect.y - rect.height / 2) / rect.height)),
      };
      if (!frame) frame = requestAnimationFrame(draw);
    };
    const visibility = () => {
      if (document.hidden) reset();
    };
    const enter = () => {
      setGreeting(true);
      clearTimeout(wave.current);
      wave.current = setTimeout(() => setGreeting(false), 1500);
    };
    const connect = () => {
      reset();
      window.removeEventListener('pointermove', move);
      if (!motion.matches) window.addEventListener('pointermove', move, { passive: true });
    };
    connect();
    motion.addEventListener('change', connect);
    document.addEventListener('visibilitychange', visibility);
    document.documentElement.addEventListener('pointerleave', reset);
    node.addEventListener('pointerenter', enter);
    node.addEventListener('pointerdown', enter);
    return () => {
      reset();
      window.removeEventListener('pointermove', move);
      motion.removeEventListener('change', connect);
      document.removeEventListener('visibilitychange', visibility);
      document.documentElement.removeEventListener('pointerleave', reset);
      node.removeEventListener('pointerenter', enter);
      node.removeEventListener('pointerdown', enter);
      clearTimeout(wave.current);
    };
  }, [active, fallback, headOnly]);
  return (
    <div
      ref={root}
      className={`buddy-rig ${headOnly ? 'head-only' : ''} ${className} ${greeting ? 'is-waving' : ''}`}
      data-state={state}
      aria-hidden={decorative || headOnly ? true : undefined}
    >
      {fallback ? (
        <img className="buddy-static" src="/assets/rag-buddy-640.webp" alt="" />
      ) : (
        <>
          {!headOnly && (
            <>
              <img
                className="buddy-body"
                src="/assets/buddy-rig/body.webp"
                alt=""
                onError={() => setFallback(true)}
              />
              <img
                className="buddy-hand"
                src="/assets/buddy-rig/hand.webp"
                alt=""
                onError={() => setFallback(true)}
              />
            </>
          )}
          <div className="buddy-head">
            <img src="/assets/buddy-rig/head.webp" alt="" onError={() => setFallback(true)} />
            <span className="buddy-pupil pupil-left" />
            <span className="buddy-pupil pupil-right" />
          </div>
        </>
      )}
      {!headOnly && !decorative && (
        <span className="buddy-greeting" role="status">
          {greeting
            ? 'สวัสดี ไปเรียนรู้ด้วยกัน!'
            : state === 'thinking'
              ? 'กำลังทำงานจากคลิปที่เลือก…'
              : state === 'error'
                ? 'ลองตรวจข้อความด้านล่างนะ'
                : state === 'success'
                  ? 'งานเสร็จแล้ว ลองตรวจผลลัพธ์'
                  : 'เพื่อนคู่คิดจากคลิปโปรด'}
        </span>
      )}
    </div>
  );
}

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
    // The oversized artwork is decorative. Listen on its bounded scene container
    // so it can react to the pointer without covering navigation or form controls.
    const interactionSurface = node.parentElement || node;
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0,
      pending = { x: 0, y: 0 };
    const draw = () => {
      frame = 0;
      node.style.setProperty('--eye-x', `${pending.x * 6}px`);
      node.style.setProperty('--eye-y', `${pending.y * 5}px`);
      node.style.setProperty('--head-tilt', `${pending.x * 1.5}deg`);
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
    interactionSurface.addEventListener('pointerenter', enter);
    interactionSurface.addEventListener('pointerdown', enter);
    return () => {
      reset();
      window.removeEventListener('pointermove', move);
      motion.removeEventListener('change', connect);
      document.removeEventListener('visibilitychange', visibility);
      document.documentElement.removeEventListener('pointerleave', reset);
      interactionSurface.removeEventListener('pointerenter', enter);
      interactionSurface.removeEventListener('pointerdown', enter);
      clearTimeout(wave.current);
    };
  }, [active, fallback, headOnly]);
  return (
    <div
      ref={root}
      className={`buddy-rig ${headOnly ? 'head-only' : 'buddy-scene'} ${className} ${greeting ? 'is-waving' : ''}`}
      data-state={state}
      aria-hidden={decorative || headOnly ? true : undefined}
    >
      {fallback ? (
        <img className="buddy-static" src="/assets/rag-buddy-640.webp" alt="" />
      ) : headOnly ? (
        <img
          className="buddy-avatar-image"
          src="/assets/buddy-reference/avatar-256.webp"
          width="256"
          height="256"
          alt=""
          onError={() => setFallback(true)}
        />
      ) : (
        <img
          className="buddy-scene-image"
          src="/assets/buddy-reference/scene-1536.webp"
          srcSet="/assets/buddy-reference/scene-768.webp 768w, /assets/buddy-reference/scene-1536.webp 1536w"
          sizes="(max-width: 600px) 100vw, 65vw"
          width="1536"
          height="1024"
          fetchPriority="high"
          alt=""
          onError={() => setFallback(true)}
        />
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

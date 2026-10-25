import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { createPortal } from 'react-dom';
import InteractiveBuddy from './InteractiveBuddy';
import type { BuddyState } from './InteractiveBuddy';
import { ResultView } from './Results';
import { clampPoint, cornerPoint, isDrag, readPosition, shouldSend } from './buddyModel';
import type { Point, Viewport } from './buddyModel';
import type { TaskResult, Video } from './types';
import { statusLabels, videoQueryable } from './domain';
import { SourceBadges } from './Evidence';

export interface BuddyTurn {
  id: string;
  label: string;
  result: TaskResult;
  partial: boolean;
  sources: { video_id: string }[];
}
interface Props {
  open: boolean;
  onOpen: (value: boolean) => void;
  videos: Video[];
  selected: string[];
  select: (id: string) => void;
  question: string;
  change: (text: string) => void;
  submit: (event: FormEvent) => void;
  turns: BuddyTurn[];
  locked: boolean;
  busy: boolean;
  status: string;
  error: string;
  waiting?: { id: string; label: string; status: string; follow: () => void }[];
  scopeNotice: string;
  newConversation: () => void;
  cancel?: () => void;
  retry?: () => void;
  fullChat: () => void;
  history: () => void;
  historyAvailable: boolean;
  historyPending: boolean;
}
function viewport(): Viewport {
  const view = window.visualViewport;
  return {
    left: view?.offsetLeft || 0,
    top: view?.offsetTop || 0,
    width: view?.width || innerWidth,
    height: view?.height || innerHeight,
  };
}
function storage() {
  try {
    return localStorage;
  } catch {
    return undefined;
  }
}
export default function FloatingBuddy(props: Props) {
  const { open, onOpen } = props;
  const [view, setView] = useState(viewport);
  const [point, setPoint] = useState(() => readPosition(storage(), viewport()));
  const current = useRef(point);
  const preferred = useRef(point);
  const [dragging, setDragging] = useState(false);
  const launcher = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  const savedScroll = useRef(0);
  const observedCount = useRef(0);
  const [newMessage, setNewMessage] = useState(false);
  const drag = useRef<{ pointer: number; start: Point; origin: Point; moved: boolean } | null>(
    null,
  );
  const ignoreClick = useRef(false);
  const frame = useRef(0);
  const queued = useRef(point);
  const mobile = view.width < 600;
  const state: BuddyState = props.busy
    ? 'thinking'
    : props.error
      ? 'error'
      : props.turns.length
        ? 'success'
        : 'idle';
  const apply = (value: Point, save = false) => {
    const next = clampPoint(value, viewport());
    current.current = next;
    preferred.current = next;
    setPoint(next);
    if (save) {
      try {
        storage()?.setItem('ragbuddy.launcher.v1', JSON.stringify({ v: 1, x: next.x, y: next.y }));
      } catch {
        /* Optional preference only. */
      }
    }
  };
  function close() {
    onOpen(false);
    requestAnimationFrame(() => launcher.current?.focus());
  }
  useEffect(() => {
    let resizeFrame = 0;
    const resize = () => {
      // Coalesce transient visual-viewport changes before clamping the saved position.
      cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        const next = viewport();
        if (next.width <= 0 || next.height <= 0) return;
        setView(next);
        // Temporary viewport sizes must not overwrite the user's chosen position.
        const visible = clampPoint(preferred.current, next);
        current.current = visible;
        setPoint(visible);
      });
    };
    const avoidFocus = (event: FocusEvent) => {
      if (!(event.target instanceof HTMLElement) || event.target.closest('.buddy-widget')) return;
      // Focusing the document after a screenshot or navigation is not an obscured control.
      if (
        !event.target.matches(
          'a[href],button,input,textarea,select,summary,[contenteditable="true"],[tabindex]:not([tabindex="-1"])',
        )
      )
        return;
      const rect = event.target.getBoundingClientRect(),
        button = launcher.current?.getBoundingClientRect();
      if (
        button &&
        rect.right > button.left &&
        rect.left < button.right &&
        rect.bottom > button.top &&
        rect.top < button.bottom
      ) {
        const view = viewport();
        const headerBottom = document.querySelector('.topbar')?.getBoundingClientRect().bottom || 0;
        for (const corner of ['bottom-right', 'bottom-left', 'top-left', 'top-right']) {
          let candidate = cornerPoint(corner, view);
          if (corner.startsWith('top'))
            candidate = clampPoint(
              { ...candidate, y: Math.max(candidate.y, headerBottom + 16) },
              view,
            );
          if (
            rect.right <= candidate.x ||
            rect.left >= candidate.x + 72 ||
            rect.bottom <= candidate.y ||
            rect.top >= candidate.y + 72
          ) {
            apply(candidate);
            break;
          }
        }
      }
    };
    window.addEventListener('resize', resize);
    window.visualViewport?.addEventListener('resize', resize);
    window.visualViewport?.addEventListener('scroll', resize);
    document.addEventListener('focusin', avoidFocus);
    return () => {
      cancelAnimationFrame(resizeFrame);
      cancelAnimationFrame(frame.current);
      window.removeEventListener('resize', resize);
      window.visualViewport?.removeEventListener('resize', resize);
      window.visualViewport?.removeEventListener('scroll', resize);
      document.removeEventListener('focusin', avoidFocus);
    };
  }, []);
  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector<HTMLButtonElement>('button')?.focus();
    if (!mobile) return;
    const roots = [...document.querySelectorAll<HTMLElement>('.app-shell')];
    roots.forEach((node) => {
      node.inert = true;
    });
    return () =>
      roots.forEach((node) => {
        node.inert = false;
      });
  }, [open, mobile]);
  useLayoutEffect(() => {
    if (!open || !scroller.current) return;
    const incoming = props.turns.length > observedCount.current;
    observedCount.current = props.turns.length;
    if (atBottom.current) scroller.current.scrollTop = scroller.current.scrollHeight;
    else {
      scroller.current.scrollTop = savedScroll.current;
      if (incoming) setNewMessage(true);
    }
  }, [props.turns.length, props.status, open]);
  const width = Math.min(view.width >= 1200 ? 460 : 400, view.width - 24);
  const height = Math.min(700, view.height - (mobile ? 24 : 112));
  const x = mobile
    ? view.left + 12
    : Math.max(
        view.left + 16,
        Math.min(
          point.x > view.left + view.width / 2 ? point.x + 72 - width : point.x,
          view.left + view.width - width - 16,
        ),
      );
  const y = mobile
    ? view.top + view.height - height - 12
    : Math.max(
        view.top + 16,
        Math.min(point.y - height - 12, view.top + view.height - height - 16),
      );
  const finish = (event: React.PointerEvent<HTMLButtonElement>, cancelled: boolean) => {
    const pending = drag.current;
    if (!pending || pending.pointer !== event.pointerId) return;
    cancelAnimationFrame(frame.current);
    frame.current = 0;
    drag.current = null;
    setDragging(false);
    ignoreClick.current = pending.moved;
    apply(
      cancelled ? pending.origin : pending.moved ? queued.current : pending.origin,
      !cancelled && pending.moved,
    );
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  };
  return createPortal(
    <div className="buddy-widget">
      <button
        ref={launcher}
        className={`buddy-launcher ${dragging ? 'is-dragging' : ''}`}
        aria-label={open ? 'ย่อแชต Buddy' : 'เปิดแชต Buddy แบบลอย'}
        aria-expanded={open}
        aria-controls="floating-buddy-chat"
        aria-describedby="buddy-position-help"
        aria-keyshortcuts="ArrowUp ArrowDown ArrowLeft ArrowRight Home"
        title="แชตกับ Buddy · ลากเพื่อย้ายตำแหน่ง"
        onKeyDown={(event) => {
          const steps: Record<string, Point> = {
            ArrowUp: { x: 0, y: -1 },
            ArrowDown: { x: 0, y: 1 },
            ArrowLeft: { x: -1, y: 0 },
            ArrowRight: { x: 1, y: 0 },
          };
          if (event.key === 'Home') {
            event.preventDefault();
            apply(cornerPoint('bottom-right', viewport()), true);
          } else if (steps[event.key]) {
            event.preventDefault();
            const delta = steps[event.key],
              distance = event.shiftKey ? 40 : 10;
            apply(
              {
                x: current.current.x + delta.x * distance,
                y: current.current.y + delta.y * distance,
              },
              true,
            );
          }
        }}
        style={{ left: point.x, top: point.y }}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          ignoreClick.current = false;
          drag.current = {
            pointer: event.pointerId,
            start: { x: event.clientX, y: event.clientY },
            origin: current.current,
            moved: false,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const pending = drag.current;
          if (!pending || pending.pointer !== event.pointerId) return;
          const end = { x: event.clientX, y: event.clientY };
          if (!pending.moved && !isDrag(pending.start, end)) return;
          pending.moved = true;
          setDragging(true);
          queued.current = clampPoint(
            {
              x: pending.origin.x + end.x - pending.start.x,
              y: pending.origin.y + end.y - pending.start.y,
            },
            viewport(),
          );
          if (!frame.current)
            frame.current = requestAnimationFrame(() => {
              frame.current = 0;
              apply(queued.current);
            });
        }}
        onPointerUp={(event) => finish(event, false)}
        onPointerCancel={(event) => finish(event, true)}
        onLostPointerCapture={(event) => {
          if (drag.current) finish(event, true);
        }}
        onClick={(event) => {
          if (event.detail && ignoreClick.current) {
            ignoreClick.current = false;
            return;
          }
          onOpen(!open);
        }}
      >
        <InteractiveBuddy headOnly active={false} decorative state={state} />
      </button>
      <span id="buddy-position-help" className="visually-hidden">
        กด Enter เพื่อเปิดหรือย่อแชต ใช้ปุ่มลูกศรเพื่อย้ายตำแหน่ง และ Home เพื่อกลับมุมขวาล่าง
      </span>
      {open && (
        <>
          {mobile && <div className="buddy-modal-scrim" onClick={close} />}
          <section
            id="floating-buddy-chat"
            ref={panel}
            className={`buddy-panel ${mobile ? 'is-mobile' : ''}`}
            role="dialog"
            aria-label="Buddy AI แชตจากคลิป"
            aria-modal={mobile ? true : undefined}
            data-compact={view.height < 450}
            style={{ left: x, top: y, width, height, minHeight: Math.min(240, height) }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.stopPropagation();
                close();
              }
              if (mobile && event.key === 'Tab') {
                const items = [
                  ...panel.current!.querySelectorAll<HTMLElement>(
                    'button:not(:disabled),textarea:not(:disabled),input:not(:disabled),a[href],summary',
                  ),
                ].filter((node) => node.getClientRects().length);
                const first = items[0],
                  last = items.at(-1);
                if (event.shiftKey && document.activeElement === first) {
                  event.preventDefault();
                  last?.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                  event.preventDefault();
                  first?.focus();
                }
              }
            }}
          >
            <header className="buddy-chat-header">
              <InteractiveBuddy headOnly active={false} decorative />
              <div>
                <strong>Buddy AI</strong>
                <small>ผู้ช่วยจากคลิปที่คุณเลือก</small>
              </div>
              <button aria-label="ย่อหน้าต่างแชต" onClick={close}>
                −
              </button>
              <button aria-label="ปิดหน้าต่างแชต" onClick={close}>
                ×
              </button>
            </header>
            <div className="buddy-chat-toolbar">
              <button
                onClick={() => {
                  props.fullChat();
                  close();
                }}
              >
                ไปหน้าแชตเต็ม ↗
              </button>
              <button disabled={props.locked} onClick={props.newConversation}>
                เริ่มบทสนทนาใหม่
              </button>
            </div>
            <details className="buddy-scope">
              <summary>คลิปที่เลือก {props.selected.length} คลิป</summary>
              <fieldset disabled={props.locked}>
                <legend>ใช้เฉพาะคลิปที่พร้อมถามตอบ</legend>
                {props.videos.map((video) => (
                  <label key={video.video_id}>
                    <input
                      type="checkbox"
                      aria-label={`ใช้คลิป ${video.title || video.video_id}`}
                      checked={props.selected.includes(video.video_id)}
                      disabled={!videoQueryable(video)}
                      onChange={() => props.select(video.video_id)}
                    />
                    <div>
                      {video.title || video.video_id}
                      <SourceBadges video={video} />
                      <small>
                        {videoQueryable(video)
                          ? 'พร้อมถามตอบ'
                          : statusLabels[video.status] || 'ยังไม่พร้อม'}
                      </small>
                    </div>
                  </label>
                ))}
                {!props.videos.length && <p>ยังไม่มีคลิปในคลัง เพิ่มคลิปก่อนเริ่มถามได้เลย</p>}
              </fieldset>
            </details>
            <div
              className="buddy-messages"
              ref={scroller}
              onScroll={() => {
                const node = scroller.current!;
                savedScroll.current = node.scrollTop;
                atBottom.current = node.scrollHeight - node.scrollTop - node.clientHeight < 56;
                if (atBottom.current) setNewMessage(false);
              }}
            >
              {!props.turns.length && (
                <div className="buddy-empty">
                  <InteractiveBuddy headOnly active={false} decorative state={state} />
                  <h3>เริ่มจากคลิปที่อยากเข้าใจ</h3>
                  <p>เลือกคลิป แล้วถาม Buddy พร้อมเปิดหลักฐานจากช่วงเวลาจริงในคลิป</p>
                </div>
              )}
              {props.turns.map((turn) => (
                <article className="buddy-message" key={turn.id}>
                  <div className="buddy-question">{turn.label}</div>
                  <small>
                    คลิปในชุดคำถามนี้:{' '}
                    {turn.sources
                      .map(
                        (source) =>
                          props.videos.find((video) => video.video_id === source.video_id)?.title ||
                          source.video_id,
                      )
                      .join(' · ')}
                  </small>
                  <div className="buddy-reply-heading">
                    <InteractiveBuddy headOnly active={false} decorative />
                    <strong>Buddy AI</strong>
                  </div>
                  <ResultView result={turn.result} partial={turn.partial} />
                </article>
              ))}
              {props.historyAvailable && (
                <button
                  className="text-button"
                  disabled={props.historyPending}
                  onClick={props.history}
                >
                  {props.historyPending ? 'กำลังโหลดประวัติ…' : 'โหลดประวัติบทสนทนานี้'}
                </button>
              )}
              {props.status && (
                <p role="status" className="buddy-job-status">
                  {props.status}
                </p>
              )}
              {props.scopeNotice && <p className="notice">{props.scopeNotice}</p>}
              {props.waiting?.map((item) => (
                <article className="deferred-jobs" key={item.id}>
                  <strong>{item.label}</strong>
                  <p role="status">{item.status}</p>
                  <button disabled={props.locked} onClick={item.follow}>
                    ติดตามงานเดิมอีกครั้ง
                  </button>
                </article>
              ))}
              {props.error && (
                <p role="alert" className="notice error">
                  {props.error}
                </p>
              )}
              {props.cancel && <button onClick={props.cancel}>ขอยกเลิกงานแชต</button>}
              {props.retry && (
                <button onClick={props.retry}>ลองติดตามหรือส่งคำขอเดิมอีกครั้ง</button>
              )}
            </div>
            {newMessage && (
              <button
                className="buddy-new-message"
                onClick={() => {
                  scroller.current!.scrollTop = scroller.current!.scrollHeight;
                  atBottom.current = true;
                  setNewMessage(false);
                }}
              >
                มีข้อความใหม่ ↓
              </button>
            )}
            <div className="buddy-suggestions">
              {['สรุปประเด็นสำคัญจากคลิป', 'ช่วยยกตัวอย่างให้เข้าใจง่าย'].map((text) => (
                <button key={text} disabled={props.locked} onClick={() => props.change(text)}>
                  {text}
                </button>
              ))}
            </div>
            <form className="buddy-composer" onSubmit={props.submit}>
              <label className="visually-hidden" htmlFor="buddy-question">
                ข้อความถึง Buddy
              </label>
              <textarea
                id="buddy-question"
                rows={2}
                value={props.question}
                disabled={props.locked}
                onChange={(event) => props.change(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    shouldSend({
                      key: event.key,
                      shiftKey: event.shiftKey,
                      isComposing: event.nativeEvent.isComposing,
                      keyCode: event.nativeEvent.keyCode,
                    })
                  ) {
                    event.preventDefault();
                    if (!props.locked && props.selected.length && props.question.trim())
                      event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder="ถาม Buddy เกี่ยวกับคลิป…"
              />
              <button
                className="primary"
                disabled={props.locked || !props.selected.length || !props.question.trim()}
                aria-label="ส่งข้อความถึง Buddy"
              >
                ➤
              </button>
            </form>
            {!props.selected.length && (
              <small className="buddy-scope-help">เลือกคลิปอย่างน้อย 1 คลิปก่อนส่งคำถาม</small>
            )}
          </section>
        </>
      )}
    </div>,
    document.body,
  );
}

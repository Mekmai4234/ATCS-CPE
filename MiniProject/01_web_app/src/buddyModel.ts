import type { Scope } from './types';
export interface Point {
  x: number;
  y: number;
}
export interface Viewport {
  left: number;
  top: number;
  width: number;
  height: number;
}
export const LAUNCHER_SIZE = 72;
export function clampPoint(point: Point, view: Viewport, size = LAUNCHER_SIZE, gap = 16): Point {
  const minX = view.left + gap,
    minY = view.top + gap;
  return {
    x: Math.min(Math.max(point.x, minX), Math.max(minX, view.left + view.width - size - gap)),
    y: Math.min(Math.max(point.y, minY), Math.max(minY, view.top + view.height - size - gap)),
  };
}
export function cornerPoint(corner: string, view: Viewport): Point {
  return clampPoint(
    {
      x: corner.includes('left') ? view.left : view.left + view.width,
      y: corner.includes('top') ? view.top : view.top + view.height,
    },
    view,
  );
}
export function readPosition(storage: Pick<Storage, 'getItem'> | undefined, view: Viewport): Point {
  try {
    const value = JSON.parse(storage?.getItem('ragbuddy.launcher.v1') || 'null');
    if (value?.v === 1 && Number.isFinite(value.x) && Number.isFinite(value.y))
      return clampPoint(value, view);
  } catch {
    /* Storage is optional. */
  }
  return cornerPoint('bottom-right', view);
}
export function scopeFingerprint(scope: Scope) {
  return JSON.stringify([
    [...scope.video_ids].sort(),
    [...scope.channel_ids].sort(),
    scope.date_from,
    scope.date_to,
  ]);
}
export const isDrag = (start: Point, end: Point) =>
  Math.hypot(end.x - start.x, end.y - start.y) >= 7;
export const shouldSend = (event: {
  key: string;
  shiftKey: boolean;
  isComposing: boolean;
  keyCode?: number;
}) => event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229;

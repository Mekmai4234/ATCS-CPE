import { describe, expect, it } from 'vitest';
import {
  clampPoint,
  cornerPoint,
  isDrag,
  readPosition,
  scopeFingerprint,
  shouldSend,
} from '../src/buddyModel';
const view = { left: 0, top: 0, width: 375, height: 667 };
describe('Buddy geometry and input', () => {
  it('clamps all edges with a full launcher and margin visible', () => {
    expect(clampPoint({ x: -500, y: 9999 }, view)).toEqual({ x: 16, y: 579 });
    expect(clampPoint({ x: 5000, y: -2 }, view)).toEqual({ x: 287, y: 16 });
  });
  it('respects visual viewport offsets and keyboard-sized heights', () => {
    expect(clampPoint({ x: 900, y: 999 }, { left: 10, top: 100, width: 340, height: 250 })).toEqual(
      { x: 262, y: 262 },
    );
  });
  it.each(['top-left', 'top-right', 'bottom-left', 'bottom-right'])(
    'provides an accessible corner preset %s',
    (corner) => {
      const point = cornerPoint(corner, view);
      expect(point.x).toBe(corner.includes('left') ? 16 : 287);
      expect(point.y).toBe(corner.includes('top') ? 16 : 579);
    },
  );
  it.each([
    'null',
    '{}',
    '{bad',
    '{"v":1,"x":"5","y":3}',
    '{"v":2,"x":1,"y":2}',
    '{"v":1,"x":null,"y":9}',
  ])('ignores corrupt/unversioned preference %s', (value) => {
    expect(readPosition({ getItem: () => value }, view)).toEqual(cornerPoint('bottom-right', view));
  });
  it('clamps saved coordinates and tolerates blocked storage', () => {
    expect(readPosition({ getItem: () => '{"v":1,"x":99999,"y":-500}' }, view)).toEqual({
      x: 287,
      y: 16,
    });
    expect(
      readPosition(
        {
          getItem: () => {
            throw Error('blocked');
          },
        },
        view,
      ),
    ).toEqual(cornerPoint('bottom-right', view));
  });
  it('distinguishes pointer jitter from drag', () => {
    expect(isDrag({ x: 0, y: 0 }, { x: 3, y: 3 })).toBe(false);
    expect(isDrag({ x: 0, y: 0 }, { x: 7, y: 0 })).toBe(true);
  });
  it('never sends during IME composition or Shift+Enter', () => {
    expect(shouldSend({ key: 'Enter', shiftKey: false, isComposing: false })).toBe(true);
    expect(shouldSend({ key: 'Enter', shiftKey: true, isComposing: false })).toBe(false);
    expect(shouldSend({ key: 'Enter', shiftKey: false, isComposing: true })).toBe(false);
    expect(shouldSend({ key: 'Enter', shiftKey: false, isComposing: false, keyCode: 229 })).toBe(
      false,
    );
  });
  it('compares the actual scope rather than selection order', () => {
    const a = { video_ids: ['a', 'b'], channel_ids: [], date_from: null, date_to: null };
    expect(scopeFingerprint(a)).toBe(scopeFingerprint({ ...a, video_ids: ['b', 'a'] }));
    expect(scopeFingerprint(a)).not.toBe(scopeFingerprint({ ...a, video_ids: ['a'] }));
    expect(scopeFingerprint(a)).not.toBe(scopeFingerprint({ ...a, date_from: '2026-01-01' }));
  });
});

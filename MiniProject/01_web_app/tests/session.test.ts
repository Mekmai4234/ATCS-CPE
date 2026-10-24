import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  DemoSessionPort,
  PendingSessionPort,
  safeMemberSession,
  safeWorkspacePath,
} from '../src/session';
import { Api, ApiError } from '../src/api';

const goodSession = () => ({
  member: {
    id: 'user-1',
    name: 'Member',
    email: 'member@example.test',
    role: 'user',
    status: 'active',
  },
  sessionId: 'opaque',
  csrfHeader: 'X-CSRF-Example',
  csrfToken: 'csrf-example',
  adminSections: [],
});

describe('session boundary', () => {
  beforeEach(() => {
    const values = new Map<string, string>();
    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => values.get(key) || null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    });
  });
  it('fails closed while the real auth contract is pending', async () => {
    const port = new PendingSessionPort();
    expect(port.ready).toBe(false);
    expect(await port.restore()).toBeNull();
    await expect(port.exchangeGoogle('unused')).rejects.toMatchObject({ code: 'auth_unavailable' });
    await expect(port.admin()).rejects.toMatchObject({ code: 'forbidden' });
  });
  it('supports relative same-origin API paths in explicit demo mode', async () => {
    const port = new DemoSessionPort();
    const session = await port.signInDemo('A');
    const api = new Api('', port.transport(session));
    expect((await api.videos()).total).toBe(2);
  });
  it('rejects malformed roles, missing CSRF and suspended members', () => {
    expect(safeMemberSession(goodSession()).member.id).toBe('user-1');
    expect(() => safeMemberSession({ ...goodSession(), csrfToken: '' })).toThrow();
    expect(() => safeMemberSession({ ...goodSession(), csrfToken: {} })).toThrow();
    expect(() =>
      safeMemberSession({ ...goodSession(), member: { ...goodSession().member, name: 42 } }),
    ).toThrow();
    expect(() => safeMemberSession({ ...goodSession(), csrfHeader: 'Bad\nHeader' })).toThrow();
    expect(() =>
      safeMemberSession({ ...goodSession(), member: { ...goodSession().member, role: 'owner' } }),
    ).toThrow();
    expect(() =>
      safeMemberSession({
        ...goodSession(),
        member: { ...goodSession().member, status: 'suspended' },
      }),
    ).toThrow();
  });
  it('uses only known internal destinations', () => {
    expect(safeWorkspacePath('/admin')).toBe('/admin');
    expect(safeWorkspacePath('//evil.example')).toBe('/');
    expect(safeWorkspacePath('https://evil.example')).toBe('/');
  });
  it('isolates demo account stores and invalidates the previous session transport', async () => {
    const port = new DemoSessionPort();
    const a = await port.signInDemo('A');
    const old = port.transport(a);
    await old('http://demo.test/api/videos/import', {
      method: 'POST',
      body: JSON.stringify({ urls: ['https://youtu.be/NoCaption01'] }),
    });
    await port.logout();
    const b = await port.signInDemo('B');
    expect((await old('http://demo.test/api/videos')).status).toBe(401);
    const library = await (await port.transport(b)('http://demo.test/api/videos')).json();
    expect(library.total).toBe(2);
    expect(sessionStorage.getItem('ragbuddy.demo.account')).toBe('B');
  });
  it('does not grant admin privileges from a user-controlled role field', async () => {
    const port = new DemoSessionPort();
    const session = await port.signInDemo('A');
    await expect(
      port.admin({ ...session, member: { ...session.member, role: 'admin' } }),
    ).rejects.toMatchObject({ code: 'forbidden' });
    const admin = await port.signInDemo('admin');
    await port.setMemberStatus(admin, 'B', 'suspended');
    await expect(port.signInDemo('B')).rejects.toMatchObject({ code: 'account_suspended' });
  });
});

describe('authenticated HTTP client', () => {
  it('expires the session even when a 401 response is not JSON', async () => {
    const expired = vi.fn();
    const api = new Api(
      'http://api.test',
      async () => new Response('Unauthorized', { status: 401 }),
      1000,
      {
        csrf: () => ({ header: 'X-CSRF', token: 'nonce' }),
        onSessionExpired: expired,
      },
    );
    await expect(api.videos()).rejects.toMatchObject({
      code: 'invalid_response',
      retryable: false,
    });
    expect(expired).toHaveBeenCalledOnce();
  });
  it('includes cookies and the negotiated CSRF header for mutations without ownership fields', async () => {
    const send = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify({ answer: 'OK' })),
    );
    const api = new Api('http://api.test', send, 1000, {
      csrf: () => ({ header: 'X-CSRF-Example', token: 'nonce' }),
      onSessionExpired: vi.fn(),
    });
    await api.submit('/api/chat', { question: 'Q', scope: { video_ids: ['v'] } }, 'key');
    const init = send.mock.calls[0][1]!;
    expect(init.credentials).toBe('include');
    expect(new Headers(init.headers).get('X-CSRF-Example')).toBe('nonce');
    expect(JSON.parse(String(init.body))).not.toHaveProperty('user_id');
    expect(JSON.parse(String(init.body))).not.toHaveProperty('role');
  });
  it('refuses mutations with no CSRF token before network I/O', async () => {
    const send = vi.fn();
    const api = new Api('http://api.test', send, 1000, {
      csrf: () => ({ header: 'X-CSRF', token: '' }),
      onSessionExpired: vi.fn(),
    });
    await expect(api.submit('/api/chat', {}, 'key')).rejects.toMatchObject({
      code: 'csrf_missing',
    });
    expect(send).not.toHaveBeenCalled();
  });
  it.each([401, 403])(
    'never marks HTTP %i retryable and only expires the session on 401',
    async (status) => {
      const expired = vi.fn();
      const send = vi.fn(
        async () =>
          new Response(
            JSON.stringify({ error: { code: 'auth', message: 'Denied', retryable: true } }),
            { status },
          ),
      );
      const api = new Api('http://api.test', send, 1000, {
        csrf: () => ({ header: 'X-CSRF', token: 'nonce' }),
        onSessionExpired: expired,
      });
      await expect(api.videos()).rejects.toMatchObject({ retryable: false });
      expect(send).toHaveBeenCalledTimes(1);
      expect(expired).toHaveBeenCalledTimes(status === 401 ? 1 : 0);
    },
  );
  it('aborts outstanding requests and rejects future work after disposal', async () => {
    const send = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () =>
            reject(new DOMException('Aborted', 'AbortError')),
          );
        }),
    );
    const api = new Api('http://api.test', send);
    const outstanding = api.videos();
    api.dispose();
    await expect(outstanding).rejects.toMatchObject({ name: 'AbortError' });
    await expect(api.videos()).rejects.toMatchObject({ name: 'AbortError' });
    expect(send).toHaveBeenCalledTimes(1);
  });
});

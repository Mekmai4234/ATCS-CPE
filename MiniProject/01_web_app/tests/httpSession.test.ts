import { afterEach, describe, expect, it, vi } from 'vitest';
import { HttpSessionPort } from '../src/httpSession';
import type { Transport } from '../src/api';

const user = {
  user_id: 'member-01',
  name: null,
  email: null,
  picture: null,
  role: 'user',
  status: 'active',
};
const session = { user, csrf_token: 'session-csrf' };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
function setup() {
  const send = vi.fn<Transport>(async (input) => {
    const path = new URL(String(input)).pathname;
    if (path.endsWith('/challenge'))
      return json({ nonce: 'server-nonce', csrf_token: 'login-csrf', client_id: 'server-client' });
    if (path.endsWith('/logout')) return json({ logged_out: true });
    if (path.endsWith('/stats')) return json({ users: 120, jobs: { queued: 3, running: 2 } });
    if (path.endsWith('/users')) return json({ items: [user], limit: 50, offset: 50 });
    return json(session);
  });
  return { port: new HttpSessionPort('http://api.test', send), send };
}
afterEach(() => vi.restoreAllMocks());

describe('module-02 HTTP session contract', () => {
  it('maps user_id, null profile and a non-secret client revision', async () => {
    const { port, send } = setup();
    const a = await port.restore();
    expect(a?.member).toMatchObject({
      id: 'member-01',
      name: 'สมาชิก Video Buddy',
      email: 'ไม่ได้ระบุอีเมล',
    });
    expect(a?.sessionId).not.toBe(session.csrf_token);
    expect((await port.restore())?.sessionId).not.toBe(a?.sessionId);
    expect(send.mock.calls[0][1]).toMatchObject({ credentials: 'include', cache: 'no-store' });
  });
  it('returns guest only for 401, while network errors remain visible', async () => {
    const { port, send } = setup();
    send.mockResolvedValueOnce(new Response('Unauthorized', { status: 401 }));
    expect(await port.restore()).toBeNull();
    send.mockRejectedValueOnce(new Error('offline'));
    await expect(port.restore()).rejects.toMatchObject({ code: 'network_error' });
  });
  it('uses the server nonce and login CSRF, consumes the challenge once and never supplies identity fields', async () => {
    const { port, send } = setup();
    expect(await port.challenge()).toEqual({ nonce: 'server-nonce', clientId: 'server-client' });
    await port.exchangeGoogle('transient-credential');
    const [, init] = send.mock.calls.at(-1)!;
    expect(JSON.parse(String(init?.body))).toEqual({
      credential: 'transient-credential',
      csrf_token: 'login-csrf',
    });
    expect(init?.credentials).toBe('include');
    await expect(port.exchangeGoogle('replay')).rejects.toMatchObject({
      code: 'challenge_expired',
    });
    expect(send).toHaveBeenCalledTimes(2);
  });
  it('requires a fresh challenge after failed delivery', async () => {
    const { port, send } = setup();
    await port.challenge();
    send.mockRejectedValueOnce(new Error('offline'));
    await expect(port.exchangeGoogle('once')).rejects.toMatchObject({ code: 'network_error' });
    await expect(port.exchangeGoogle('again')).rejects.toMatchObject({ code: 'challenge_expired' });
    await port.challenge();
    expect((await port.exchangeGoogle('new')).member.id).toBe(user.user_id);
  });
  it('rejects expired and malformed challenges before exchanging a token', async () => {
    const { port, send } = setup();
    await port.challenge();
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 241000);
    await expect(port.exchangeGoogle('old')).rejects.toMatchObject({ code: 'challenge_expired' });
    send.mockResolvedValueOnce(json({ nonce: '', csrf_token: 'csrf', client_id: 'id' }));
    await expect(port.challenge()).rejects.toMatchObject({ code: 'invalid_challenge' });
  });
  it('sends logout CSRF and cookies; an already revoked session counts as signed out', async () => {
    const { port, send } = setup();
    await port.restore();
    await port.logout();
    expect(new Headers(send.mock.calls.at(-1)![1]?.headers).get('X-CSRF-Token')).toBe(
      'session-csrf',
    );
    await port.restore();
    send.mockResolvedValueOnce(json({ error: { code: 'authentication_required' } }, 401));
    await expect(port.logout()).resolves.toBeUndefined();
  });
  it('retains the CSRF token for manual retry when logout fails', async () => {
    const { port, send } = setup();
    await port.restore();
    send.mockResolvedValueOnce(json({ error: { code: 'unavailable' } }, 503));
    await expect(port.logout()).rejects.toMatchObject({ status: 503 });
    await port.logout();
    expect(new Headers(send.mock.calls.at(-1)![1]?.headers).get('X-CSRF-Token')).toBe(
      'session-csrf',
    );
  });
  it('maps real admin stats, server search/pagination and supported menus only', async () => {
    const { port, send } = setup();
    send.mockResolvedValueOnce(json({ ...session, user: { ...user, role: 'admin' } }));
    const admin = (await port.restore())!;
    expect(admin.adminSections).toEqual(['overview', 'members']);
    const data = await port.admin(admin, undefined, 'member name', 50);
    expect(data.stats).toEqual({ users: 120, jobs: { queued: 3, running: 2 } });
    expect(
      send.mock.calls.some(([url]) => String(url).includes('q=member+name&limit=50&offset=50')),
    ).toBe(true);
  });
  it('uses the real member update endpoint and session CSRF for role/status changes', async () => {
    const { port, send } = setup();
    const admin = (await port.restore())!;
    await port.setMemberRole(admin, 'target/id', 'admin');
    expect(String(send.mock.calls.at(-1)![0]).endsWith('/api/admin/users/target%2Fid')).toBe(true);
    expect(JSON.parse(String(send.mock.calls.at(-1)![1]?.body))).toEqual({ role: 'admin' });
    await port.setMemberStatus(admin, 'target', 'suspended');
    expect(JSON.parse(String(send.mock.calls.at(-1)![1]?.body))).toEqual({ status: 'suspended' });
    expect(new Headers(send.mock.calls.at(-1)![1]?.headers).get('X-CSRF-Token')).toBe(
      'session-csrf',
    );
  });
  it('rejects invalid member/session data rather than granting workspace access', async () => {
    const { port, send } = setup();
    send.mockResolvedValueOnce(json({ ...session, user: { ...user, role: 'owner' } }));
    await expect(port.restore()).rejects.toMatchObject({ code: 'invalid_session' });
    send.mockResolvedValueOnce(json({ ...session, csrf_token: '' }));
    await expect(port.restore()).rejects.toMatchObject({ code: 'invalid_session' });
  });
});

import { Api, ApiError } from './api';
import type { Transport } from './api';
import { safeMemberSession } from './session';
import type { AdminSnapshot, LoginChallenge, Member, MemberSession, SessionPort } from './session';

type ServerUser = {
  user_id: string;
  name: string | null;
  email: string | null;
  picture: string | null;
  role: Member['role'];
  status: Member['status'];
};
type ServerSession = { user: ServerUser; csrf_token: string };
const member = (user: ServerUser): Member => ({
  id: user.user_id,
  name: user.name?.trim() || user.email?.trim() || 'สมาชิก RAG Buddy',
  email: user.email?.trim() || 'ไม่ได้ระบุอีเมล',
  picture: user.picture,
  role: user.role,
  status: user.status,
});

// Contract inspected from module 02 PR18. No cookie value or Google credential is persisted.
export class HttpSessionPort implements SessionPort {
  readonly ready = true;
  readonly demo = false;
  private session: MemberSession | null = null;
  private login: { nonce: string; csrf_token: string; client_id: string; expires: number } | null =
    null;
  constructor(
    private base: string,
    private send: Transport = (input, init) => fetch(input, init),
  ) {}

  private async request<T>(
    path: string,
    init: RequestInit = {},
    authenticated = false,
  ): Promise<T> {
    const api = new Api(
      this.base,
      this.send,
      15000,
      authenticated
        ? {
            csrf: () => ({ header: 'X-CSRF-Token', token: this.session?.csrfToken || '' }),
            onSessionExpired: () => {
              this.session = null;
            },
          }
        : undefined,
    );
    try {
      const { data } = await api.request<T>(path, {
        ...init,
        credentials: 'include',
        cache: 'no-store',
      });
      return data;
    } finally {
      api.dispose();
    }
  }

  private accept(data: ServerSession): MemberSession {
    if (
      !data?.user ||
      typeof data.user.user_id !== 'string' ||
      (data.user.name !== null && typeof data.user.name !== 'string') ||
      (data.user.email !== null && typeof data.user.email !== 'string')
    )
      throw new ApiError('ตรวจสอบสมาชิกไม่ได้', 'invalid_session', false);
    this.session = safeMemberSession({
      member: member(data.user),
      sessionId: crypto.randomUUID(), // Client-only revision; never a cookie/session secret.
      csrfToken: data.csrf_token,
      csrfHeader: 'X-CSRF-Token',
      adminSections: data.user.role === 'admin' ? ['overview', 'members'] : [],
    });
    return this.session;
  }

  async restore(signal?: AbortSignal) {
    try {
      return this.accept(await this.request<ServerSession>('/api/auth/me', { signal }));
    } catch (error) {
      this.session = null;
      if (error instanceof ApiError && error.status === 401) return null;
      throw error;
    }
  }

  async challenge(signal?: AbortSignal): Promise<LoginChallenge> {
    this.login = null;
    const value = await this.request<{ nonce: string; csrf_token: string; client_id: string }>(
      '/api/auth/challenge',
      { signal },
    );
    if (
      !value ||
      ![value.nonce, value.csrf_token, value.client_id].every(
        (item) => typeof item === 'string' && item.length > 0,
      )
    )
      throw new ApiError(
        'ข้อมูลเข้าสู่ระบบไม่ถูกต้อง กรุณาลองอีกครั้ง',
        'invalid_challenge',
        false,
      );
    this.login = { ...value, expires: Date.now() + 240000 };
    return { nonce: value.nonce, clientId: value.client_id };
  }

  async exchangeGoogle(credential: string, signal?: AbortSignal) {
    const challenge = this.login;
    this.login = null; // A challenge is single-use, even after uncertain network delivery.
    if (!challenge || challenge.expires <= Date.now())
      throw new ApiError('การเข้าสู่ระบบหมดเวลา กรุณาลองอีกครั้ง', 'challenge_expired', false);
    return this.accept(
      await this.request<ServerSession>('/api/auth/google', {
        method: 'POST',
        signal,
        body: JSON.stringify({ credential, csrf_token: challenge.csrf_token }),
      }),
    );
  }

  async logout(signal?: AbortSignal) {
    try {
      await this.request('/api/auth/logout', { method: 'POST', signal }, true);
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) throw error;
    }
    this.session = null;
    this.login = null;
  }

  transport(_session: MemberSession) {
    return this.send;
  }
  async admin(
    _session: MemberSession,
    signal?: AbortSignal,
    query = '',
    offset = 0,
  ): Promise<AdminSnapshot> {
    const params = new URLSearchParams({ q: query, limit: '50', offset: String(offset) });
    const [stats, users] = await Promise.all([
      this.request<{ users: number; jobs: Record<string, number> }>(
        '/api/admin/stats',
        { signal },
        true,
      ),
      this.request<{ items: ServerUser[]; limit: number; offset: number }>(
        `/api/admin/users?${params}`,
        { signal },
        true,
      ),
    ]);
    if (
      !Array.isArray(users.items) ||
      !Number.isInteger(users.limit) ||
      users.limit < 1 ||
      !Number.isInteger(users.offset) ||
      users.offset < 0 ||
      !Number.isInteger(stats.users) ||
      !stats.jobs ||
      !Object.values(stats.jobs).every((count) => Number.isInteger(count) && count >= 0)
    )
      throw new ApiError('ข้อมูลผู้ดูแลไม่ถูกต้อง', 'invalid_response', false);
    return {
      stats,
      members: users.items.map(member),
      memberPage: {
        limit: users.limit,
        offset: users.offset,
        hasMore: users.items.length === users.limit,
      },
    };
  }
  async setMemberStatus(_session: MemberSession, id: string, status: Member['status']) {
    await this.updateMember(id, { status });
  }
  async setMemberRole(_session: MemberSession, id: string, role: Member['role']) {
    await this.updateMember(id, { role });
  }
  private async updateMember(
    id: string,
    change: { role?: Member['role']; status?: Member['status'] },
  ) {
    await this.request(
      `/api/admin/users/${encodeURIComponent(id)}`,
      { method: 'POST', body: JSON.stringify(change) },
      true,
    );
  }
}

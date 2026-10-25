import { ApiError } from './api';
import { demoTransport } from './demo';
import type { Transport } from './api';

export interface Member {
  id: string;
  name: string;
  email: string;
  picture?: string | null;
  role: 'user' | 'admin';
  status: 'active' | 'suspended';
}
export type AdminSection = 'overview' | 'members' | 'videos' | 'jobs' | 'audit';
export interface MemberSession {
  member: Member;
  sessionId: string;
  csrfToken: string;
  csrfHeader: string;
  adminSections: AdminSection[];
}
export interface AdminSnapshot {
  stats?: { users: number; jobs: Record<string, number> };
  memberPage?: { offset: number; limit: number; hasMore: boolean };
  members: Member[];
  videos?: { id: string; title: string; status: string }[];
  jobs?: { id: string; kind: string; state: string }[];
  audit?: { id: string; action: string; target: string; timestamp: string }[];
}

// This is a frontend port, not an assumed module-02 HTTP contract. A real adapter
// must map the team's verified contract here before production login is enabled.
export interface SessionPort {
  readonly evidence?: import('./types').EvidenceBridge;
  readonly ready: boolean;
  readonly demo: boolean;
  challenge?(signal?: AbortSignal): Promise<LoginChallenge>;
  restore(signal?: AbortSignal): Promise<MemberSession | null>;
  exchangeGoogle(credential: string, signal?: AbortSignal): Promise<MemberSession>;
  logout(signal?: AbortSignal): Promise<void>;
  transport(session: MemberSession): Transport | undefined;
  admin(
    session: MemberSession,
    signal?: AbortSignal,
    query?: string,
    offset?: number,
  ): Promise<AdminSnapshot>;
  setMemberStatus(session: MemberSession, id: string, status: Member['status']): Promise<void>;
  setMemberRole?(session: MemberSession, id: string, role: Member['role']): Promise<void>;
}

export interface LoginChallenge {
  nonce: string;
  clientId: string;
}

export class PendingSessionPort implements SessionPort {
  readonly ready = false;
  readonly demo = false;
  async restore() {
    return null;
  }
  async exchangeGoogle(_credential: string): Promise<MemberSession> {
    throw new ApiError(
      'การเข้าสู่ระบบยังไม่พร้อมใช้งาน กรุณาลองอีกครั้งภายหลัง',
      'auth_unavailable',
      false,
    );
  }
  async logout() {}
  transport() {
    return undefined;
  }
  async admin(): Promise<AdminSnapshot> {
    throw new ApiError('ไม่มีสิทธิ์เข้าถึง', 'forbidden', false);
  }
  async setMemberStatus() {
    throw new ApiError('ไม่มีสิทธิ์เข้าถึง', 'forbidden', false);
  }
}

const DEMO_ACCOUNT_KEY = 'ragbuddy.demo.account';
const demoMembers: Member[] = [
  { id: 'A', name: 'เมย์', email: 'may@example.test', role: 'user', status: 'active' },
  { id: 'B', name: 'ต้น', email: 'ton@example.test', role: 'user', status: 'active' },
  {
    id: 'admin',
    name: 'ผู้ดูแลตัวอย่าง',
    email: 'admin@example.test',
    role: 'admin',
    status: 'active',
  },
];
const allSections: AdminSection[] = ['overview', 'members', 'videos', 'jobs', 'audit'];

// Only selected in an explicitly enabled DEMO build. Storage is a public fixture
// selector, never a credential or authority in the production adapter.
export class DemoSessionPort implements SessionPort {
  readonly ready = true;
  readonly demo = true;
  private active: MemberSession | null = null;
  private members = demoMembers.map((member) => ({ ...member }));
  private transports = new Map<string, Transport>();
  private audit: NonNullable<AdminSnapshot['audit']> = [];
  async restore(signal?: AbortSignal) {
    signal?.throwIfAborted();
    const id = sessionStorage.getItem(DEMO_ACCOUNT_KEY);
    if (!id) return null;
    if (this.active?.member.id === id) return this.active;
    return this.signInDemo(id);
  }
  async signInDemo(id: string) {
    const member = this.members.find((member) => member.id === id);
    if (!member || member.status !== 'active')
      throw new ApiError('บัญชีนี้ถูกระงับการใช้งาน', 'account_suspended', false);
    this.active = {
      member: { ...member },
      sessionId: crypto.randomUUID(),
      csrfToken: crypto.randomUUID(),
      csrfHeader: 'X-Demo-CSRF',
      adminSections: member.role === 'admin' ? [...allSections] : [],
    };
    sessionStorage.setItem(DEMO_ACCOUNT_KEY, id);
    return this.active;
  }
  async exchangeGoogle(_credential: string): Promise<MemberSession> {
    throw new ApiError('โหมดตัวอย่างไม่รับ Google credential', 'demo_only', false);
  }
  async logout() {
    this.active = null;
    sessionStorage.removeItem(DEMO_ACCOUNT_KEY);
  }
  transport(session: MemberSession): Transport {
    if (!this.transports.has(session.member.id))
      this.transports.set(session.member.id, demoTransport());
    const transport = this.transports.get(session.member.id)!;
    return async (input, init) => {
      if (this.active?.sessionId !== session.sessionId)
        return new Response(
          JSON.stringify({
            error: {
              code: 'session_expired',
              message: 'กรุณาเข้าสู่ระบบอีกครั้ง',
              retryable: false,
            },
          }),
          { status: 401 },
        );
      return transport(input, init);
    };
  }
  private requireAdmin(session: MemberSession) {
    if (this.active?.sessionId !== session.sessionId || this.active.member.role !== 'admin')
      throw new ApiError('ไม่มีสิทธิ์เข้าถึง', 'forbidden', false);
  }
  async admin(session: MemberSession): Promise<AdminSnapshot> {
    this.requireAdmin(session);
    return {
      members: this.members.map((member) => ({ ...member })),
      videos: [],
      jobs: [],
      audit: [...this.audit],
    };
  }
  async setMemberStatus(session: MemberSession, id: string, status: Member['status']) {
    this.requireAdmin(session);
    const target = this.members.find((member) => member.id === id);
    if (!target || target.role === 'admin')
      throw new ApiError('เปลี่ยนสถานะบัญชีนี้ไม่ได้', 'forbidden', false);
    target.status = status;
    this.audit.unshift({
      id: crypto.randomUUID(),
      action: status === 'active' ? 'เปิดใช้บัญชี' : 'ระงับบัญชี',
      target: target.name,
      timestamp: new Date().toISOString(),
    });
  }
}

export function safeMemberSession(value: unknown): MemberSession {
  if (!value || typeof value !== 'object')
    throw new ApiError('ตรวจสอบสมาชิกไม่ได้', 'invalid_session', false);
  const session = value as MemberSession;
  const text = (value: unknown, max: number) =>
    typeof value === 'string' && value.length > 0 && value.length <= max;
  if (
    !session.member ||
    !['user', 'admin'].includes(session.member.role) ||
    !['active', 'suspended'].includes(session.member.status) ||
    !text(session.member.id, 256) ||
    !text(session.member.name, 200) ||
    !text(session.member.email, 320) ||
    !text(session.sessionId, 512) ||
    !text(session.csrfToken, 4096) ||
    /[\r\n]/.test(session.csrfToken) ||
    typeof session.csrfHeader !== 'string' ||
    !/^[A-Za-z][A-Za-z0-9-]*$/.test(session.csrfHeader) ||
    !Array.isArray(session.adminSections) ||
    session.adminSections.some((section) => !allSections.includes(section))
  ) {
    throw new ApiError('ตรวจสอบสมาชิกไม่ได้', 'invalid_session', false);
  }
  if (session.member.status !== 'active')
    throw new ApiError('บัญชีนี้ถูกระงับการใช้งาน', 'account_suspended', false);
  return session;
}

export const safeWorkspacePath = (path: string) =>
  ['/', '/library', '/chat', '/learning', '/admin'].includes(path) ? path : '/';

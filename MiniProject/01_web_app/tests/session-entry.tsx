// Test-only server contract. These /__test__/ paths are not module-02 endpoints.
import { createRoot } from 'react-dom/client';
import SessionShell from '../src/SessionShell';
import { DemoSessionPort, PendingSessionPort, safeMemberSession } from '../src/session';
import type { SessionPort, MemberSession, AdminSnapshot, Member } from '../src/session';
import { ApiError } from '../src/api';
import { visualFixture } from './visual-fixture';
import '@fontsource/ibm-plex-sans-thai/400.css';
import '@fontsource/ibm-plex-sans-thai/600.css';
import '@fontsource/ibm-plex-sans-thai/700.css';
import '@fontsource-variable/manrope';
import '@fontsource/kanit/thai-700.css';
import '@fontsource/kanit/thai-800.css';
import '../src/styles.css';
import '../src/theme.css';
import '../src/mint.css';
import '../src/polish.css';
import '../src/v5.css';
import '../src/results-v5.css';
import '../src/secondary-v5.css';
import '../src/auth-v5.css';
import '../src/job-recovery.css';

class FixtureSessionPort implements SessionPort {
  readonly evidence = new URLSearchParams(location.search).has('visual')
    ? visualFixture
    : undefined;
  readonly demo = false;
  readonly ready = true;
  private session: MemberSession | null = null;
  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`/__test__/${path}`, {
      ...init,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...init.headers },
    });
    const data = await response.json();
    if (!response.ok)
      throw new ApiError(
        data.error?.message || 'Session request failed',
        data.error?.code || 'auth_error',
        false,
        undefined,
        undefined,
        response.status,
      );
    return data as T;
  }
  async restore(signal?: AbortSignal) {
    const value = await this.request<MemberSession | null>('session', { signal });
    this.session = value ? safeMemberSession(value) : null;
    return this.session;
  }
  async exchangeGoogle(credential: string, signal?: AbortSignal) {
    const csrf = await this.request<{ token: string }>('csrf', { signal });
    this.session = safeMemberSession(
      await this.request('google', {
        method: 'POST',
        signal,
        headers: { 'X-Test-Login-CSRF': csrf.token },
        body: JSON.stringify({ credential }),
      }),
    );
    return this.session;
  }
  async logout(signal?: AbortSignal) {
    await this.request('logout', {
      method: 'POST',
      signal,
      headers: this.session ? { [this.session.csrfHeader]: this.session.csrfToken } : {},
    });
    this.session = null;
  }
  transport() {
    return undefined;
  }
  async admin(session: MemberSession, signal?: AbortSignal) {
    return this.request<AdminSnapshot>('admin', {
      signal,
      headers: { [session.csrfHeader]: session.csrfToken },
    });
  }
  async setMemberStatus(session: MemberSession, id: string, status: Member['status']) {
    await this.request('admin/member', {
      method: 'POST',
      headers: { [session.csrfHeader]: session.csrfToken },
      body: JSON.stringify({ id, status }),
    });
  }
}
const query = new URLSearchParams(window.location.search);
const port = query.has('demo')
  ? new DemoSessionPort()
  : query.has('pending')
    ? new PendingSessionPort()
    : new FixtureSessionPort();
createRoot(document.getElementById('root')!).render(<SessionShell port={port} />);

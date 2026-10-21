import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import App from './App';
import AdminView from './AdminView';
import { Api, ApiError } from './api';
import { BuddyLogo, ForestBackdrop, Mascot } from './Forest';
import GoogleButton from './GoogleButton';
import {
  DemoSessionPort,
  PendingSessionPort,
  safeMemberSession,
  safeWorkspacePath,
} from './session';
import type { MemberSession, SessionPort } from './session';

const defaultPort: SessionPort =
  import.meta.env.VITE_DEMO_MODE === 'true' ? new DemoSessionPort() : new PendingSessionPort();
const routeView = (path: string) =>
  path === '/chat'
    ? 'chat'
    : path === '/learning'
      ? 'learn'
      : path === '/library'
        ? 'library'
        : 'home';

function MemberArea({
  session,
  port,
  path,
  navigate,
  logout,
  expired,
}: {
  session: MemberSession;
  port: SessionPort;
  path: string;
  navigate: (path: string) => void;
  logout: () => void;
  expired: () => void;
}) {
  const api = useMemo(
    () =>
      new Api(import.meta.env.NEXT_PUBLIC_API_BASE_URL, port.transport(session), 75000, {
        csrf: () => ({ token: session.csrfToken, header: session.csrfHeader }),
        onSessionExpired: expired,
      }),
    [session, port, expired],
  );
  useEffect(() => () => api.dispose(), [api]);
  if (path === '/admin') {
    if (session.member.role !== 'admin' || !session.adminSections.length)
      return (
        <div className="gate-screen">
          <ForestBackdrop />
          <section className="gate-card">
            <h1>ไม่มีสิทธิ์เข้าถึงหน้านี้</h1>
            <p>พื้นที่นี้สำหรับผู้ดูแลระบบที่ได้รับสิทธิ์เท่านั้น</p>
            <button className="primary" onClick={() => navigate('/')}>
              กลับพื้นที่เรียนรู้
            </button>
          </section>
        </div>
      );
    return (
      <AdminView
        session={session}
        port={port}
        onHome={() => navigate('/')}
        onLogout={logout}
        onSessionExpired={expired}
      />
    );
  }
  return (
    <App
      api={api}
      member={session.member}
      initialView={routeView(path)}
      onNavigate={navigate}
      onLogout={logout}
      adminEnabled={session.member.role === 'admin' && !!session.adminSections.length}
    />
  );
}

export default function SessionShell({ port = defaultPort }: { port?: SessionPort }) {
  const [phase, setPhase] = useState<
    'checking' | 'guest' | 'member' | 'exchanging' | 'logging-out'
  >('checking');
  const [session, setSession] = useState<MemberSession | null>(null);
  const [message, setMessage] = useState('');
  const [path, setPath] = useState(window.location.pathname);
  const epoch = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const navigate = useCallback((next: string) => {
    const safe = next === '/login' ? '/login' : safeWorkspacePath(next);
    if (window.location.pathname !== safe) window.history.pushState(null, '', safe);
    setPath(safe);
    window.scrollTo(0, 0);
  }, []);
  const expired = useCallback(() => {
    epoch.current++;
    controller.current?.abort();
    setSession(null);
    setPhase('guest');
    setMessage('เซสชันหมดอายุ กรุณาเข้าสู่ระบบอีกครั้ง');
    navigate('/login');
  }, [navigate]);
  useEffect(() => {
    mounted.current = true;
    async function restore() {
      const ticket = ++epoch.current;
      controller.current?.abort();
      controller.current = new AbortController();
      setPhase('checking');
      setSession(null);
      try {
        const value = await port.restore(controller.current.signal);
        if (!mounted.current || ticket !== epoch.current) return;
        if (value) {
          setSession(safeMemberSession(value));
          setPhase('member');
          if (window.location.pathname === '/login') navigate('/');
        } else {
          setPhase('guest');
          navigate('/login');
        }
      } catch (error) {
        if (!mounted.current || ticket !== epoch.current) return;
        setMessage(error instanceof Error ? error.message : 'ตรวจสอบบัญชีไม่ได้ กรุณาลองอีกครั้ง');
        setPhase('guest');
        navigate('/login');
      }
    }
    const pop = () => setPath(window.location.pathname);
    const shown = (event: PageTransitionEvent) => {
      if (event.persisted) void restore();
    };
    window.addEventListener('popstate', pop);
    window.addEventListener('pageshow', shown);
    void restore();
    return () => {
      mounted.current = false;
      epoch.current++;
      controller.current?.abort();
      window.removeEventListener('popstate', pop);
      window.removeEventListener('pageshow', shown);
    };
  }, [port, navigate]);

  async function accept(getSession: (signal: AbortSignal) => Promise<MemberSession>) {
    const ticket = ++epoch.current;
    controller.current?.abort();
    controller.current = new AbortController();
    setPhase('exchanging');
    setMessage('');
    try {
      const value = safeMemberSession(await getSession(controller.current.signal));
      if (!mounted.current || ticket !== epoch.current) return;
      setSession(value);
      setPhase('member');
      navigate('/');
    } catch (error) {
      if (!mounted.current || ticket !== epoch.current) return;
      setMessage(error instanceof Error ? error.message : 'เข้าสู่ระบบไม่สำเร็จ');
      setPhase('guest');
    }
  }
  async function logout() {
    const ticket = ++epoch.current;
    controller.current?.abort();
    controller.current = new AbortController();
    setSession(null);
    setPhase('logging-out');
    navigate('/login');
    window.google?.accounts.id.disableAutoSelect();
    try {
      await port.logout(controller.current.signal);
      if (mounted.current && ticket === epoch.current) {
        setPhase('guest');
        setMessage('ออกจากระบบแล้ว');
      }
    } catch (error) {
      if (mounted.current && ticket === epoch.current)
        setMessage('ยังยืนยันการออกจากระบบไม่ได้ กรุณาลองออกจากระบบอีกครั้ง');
    }
  }

  if (phase === 'member' && session)
    return (
      <MemberArea
        key={`${session.member.id}:${session.sessionId}`}
        session={session}
        port={port}
        path={safeWorkspacePath(path)}
        navigate={navigate}
        logout={() => void logout()}
        expired={expired}
      />
    );
  const working = phase === 'checking' || phase === 'exchanging';
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';
  return (
    <div className="login-page">
      <ForestBackdrop />
      <header className="login-header">
        <BuddyLogo />
        <span>พื้นที่เล็ก ๆ สำหรับการเรียนรู้ครั้งใหญ่</span>
      </header>
      <main className="login-layout">
        <section className="login-story" aria-labelledby="login-intro">
          <span className="forest-eyebrow">YOUR KNOWLEDGE, A LITTLE MORE ALIVE.</span>
          <h1 id="login-intro">
            ทุกคำตอบ
            <br />
            มีที่มา
            <span className="coral-stroke" />
          </h1>
          <p>
            เปลี่ยนคลิปให้เป็นความรู้ของคุณ
            <br />
            เรียนรู้พร้อมหลักฐานจากคลิป
          </p>
          <Mascot />
          <span className="story-caption">พบกับ RAG Buddy · เพื่อนร่วมทางการเรียนรู้</span>
        </section>
        <section className="login-card" aria-labelledby="sign-in-title">
          <span className="login-spark" aria-hidden="true">
            ✦
          </span>
          <span className="eyebrow">WELCOME TO YOUR KNOWLEDGE FOREST</span>
          <h2 id="sign-in-title">ยินดีต้อนรับกลับ</h2>
          <p>
            เข้าสู่ระบบเพื่อเริ่มเรียนรู้จากคลิป
            <br />
            เข้าครั้งแรกก็สร้างบัญชีได้ในขั้นตอนเดียว
          </p>
          {message && (
            <p className={`notice ${message === 'ออกจากระบบแล้ว' ? '' : 'warning'}`} role="status">
              {message}
            </p>
          )}
          {working && (
            <p className="session-progress" role="status">
              {phase === 'checking' ? 'กำลังตรวจสอบเซสชัน…' : 'กำลังตรวจสอบการเข้าสู่ระบบ…'}
            </p>
          )}
          {phase === 'logging-out' && (
            <button className="secondary" onClick={() => void logout()}>
              ลองออกจากระบบอีกครั้ง
            </button>
          )}
          {phase === 'guest' && port.demo && (
            <div className="demo-login">
              <strong>DEMO · ทดลองด้วยบัญชีจำลอง</strong>
              <p>ไม่มีการใช้บัญชี Google หรือข้อมูลส่วนตัวจริง</p>
              {['A', 'B', 'admin'].map((id) => (
                <button
                  className="secondary"
                  key={id}
                  onClick={() => void accept(() => (port as DemoSessionPort).signInDemo(id))}
                >
                  {id === 'admin' ? 'ทดลองบัญชีผู้ดูแล' : `ทดลองด้วยบัญชี ${id}`}
                </button>
              ))}
            </div>
          )}
          {phase === 'guest' && !port.demo && port.ready && clientId && (
            <GoogleButton
              clientId={clientId}
              onCredential={(credential) =>
                accept((signal) => port.exchangeGoogle(credential, signal))
              }
            />
          )}
          {phase === 'guest' && !port.demo && (!port.ready || !clientId) && (
            <div className="login-unavailable" role="status">
              <span aria-hidden="true">◷</span>
              <strong>กำลังเตรียมการเข้าสู่ระบบ</strong>
              <p>
                Google Sign-In ยังไม่เปิดให้ใช้งาน
                <br />
                กรุณากลับมาใหม่เมื่อระบบพร้อม
              </p>
              <button className="secondary" disabled>
                เข้าสู่ระบบด้วย Google
              </button>
            </div>
          )}
          <div className="login-divider" />
          <p className="login-privacy">
            ใช้ Google เพื่อยืนยันตัวตนเท่านั้น
            <br />
            ไม่มีรหัสผ่านของเว็บ และไม่ขอสิทธิ์อ่าน Gmail
          </p>
          <div className="login-assurance">
            <span aria-hidden="true">⌁</span> คลังคลิปและผลการเรียนรู้เป็นของบัญชีคุณ
          </div>
        </section>
      </main>
      <footer className="login-footer">RAG Buddy · เรียนรู้ในจังหวะของคุณ</footer>
    </div>
  );
}

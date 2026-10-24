import { useEffect, useRef, useState } from 'react';
import type { LoginChallenge } from './session';

interface GoogleIdentity {
  initialize(options: {
    client_id: string;
    nonce?: string;
    callback: (response: { credential: string }) => void;
    auto_select: boolean;
    ux_mode: 'popup';
  }): void;
  renderButton(
    target: HTMLElement,
    options: {
      type: 'standard';
      theme: 'outline';
      size: 'large';
      text: 'continue_with';
      shape: 'pill';
      width: number;
      locale: string;
    },
  ): void;
  disableAutoSelect(): void;
}
declare global {
  interface Window {
    google?: { accounts: { id: GoogleIdentity } };
  }
}
let scriptPromise: Promise<void> | undefined;
function loadGoogleIdentity() {
  if (window.google?.accounts.id) return Promise.resolve();
  if (!scriptPromise)
    scriptPromise = new Promise<void>((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'https://accounts.google.com/gsi/client';
      script.async = true;
      const timer = window.setTimeout(() => {
        script.remove();
        scriptPromise = undefined;
        reject(new Error('โหลด Google Sign-In ไม่สำเร็จ ลองอีกครั้ง'));
      }, 15000);
      script.onload = () => {
        window.clearTimeout(timer);
        if (!window.google?.accounts.id) {
          script.remove();
          scriptPromise = undefined;
          reject(new Error('Google Sign-In ไม่พร้อม กรุณาลองอีกครั้ง'));
          return;
        }
        resolve();
      };
      script.onerror = () => {
        window.clearTimeout(timer);
        script.remove();
        scriptPromise = undefined;
        reject(new Error('เชื่อมต่อ Google ไม่ได้ กรุณาตรวจสอบเครือข่าย'));
      };
      document.head.appendChild(script);
    });
  return scriptPromise;
}

export default function GoogleButton({
  clientId,
  onCredential,
  prepareChallenge,
}: {
  clientId: string;
  onCredential: (credential: string) => Promise<void>;
  prepareChallenge?: (signal: AbortSignal) => Promise<LoginChallenge>;
}) {
  const target = useRef<HTMLDivElement>(null);
  const callback = useRef(onCredential);
  callback.current = onCredential;
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    let delivered = false;
    const started = Date.now();
    const controller = new AbortController();
    let refresh: ReturnType<typeof setTimeout> | undefined;
    setLoading(true);
    const prepare = async () => {
      const challenge = await prepareChallenge?.(controller.signal);
      if (!active) return;
      await loadGoogleIdentity();
      return challenge;
    };
    void prepare()
      .then((challenge) => {
        if (!active || !target.current || !window.google?.accounts.id) return;
        setLoading(false);
        window.google.accounts.id.initialize({
          client_id: challenge?.clientId || clientId,
          ...(challenge ? { nonce: challenge.nonce } : {}),
          auto_select: false,
          ux_mode: 'popup',
          callback: (response) => {
            if (active && !delivered && response.credential) {
              delivered = true;
              void callback.current(response.credential);
            }
          },
        });
        if (challenge)
          refresh = setTimeout(
            () => {
              active = false;
              target.current?.replaceChildren();
              setAttempt((value) => value + 1);
            },
            Math.max(0, 230000 - (Date.now() - started)),
          );
        window.google.accounts.id.renderButton(target.current, {
          type: 'standard',
          theme: 'outline',
          size: 'large',
          text: 'continue_with',
          shape: 'pill',
          width: Math.min(340, target.current.clientWidth || 280),
          locale: 'th',
        });
      })
      .catch((error) => {
        if (active) {
          setLoading(false);
          setError(error instanceof Error ? error.message : 'เชื่อมต่อ Google ไม่ได้');
        }
      });
    return () => {
      active = false;
      controller.abort();
      clearTimeout(refresh);
      target.current?.replaceChildren();
    };
  }, [clientId, attempt, prepareChallenge]);
  return (
    <div className="google-sign-in">
      {loading && <p role="status">กำลังเตรียม Google Sign-In…</p>}
      <div ref={target} className="google-button-host" />
      {error && (
        <div role="alert">
          <p>{error}</p>
          <button
            className="text-button"
            onClick={() => {
              setError('');
              setAttempt((value) => value + 1);
            }}
          >
            ลองโหลด Google อีกครั้ง
          </button>
        </div>
      )}
      <small>
        หากหน้าต่างเลือกบัญชีถูกปิดหรือถูกบล็อก ให้อนุญาต popup แล้วกดปุ่ม Google อีกครั้ง
      </small>
    </div>
  );
}

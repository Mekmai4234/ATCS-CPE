import { useEffect, useRef, useState } from 'react';

interface GoogleIdentity {
  initialize(options: {
    client_id: string;
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
}: {
  clientId: string;
  onCredential: (credential: string) => Promise<void>;
}) {
  const target = useRef<HTMLDivElement>(null);
  const callback = useRef(onCredential);
  callback.current = onCredential;
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void loadGoogleIdentity()
      .then(() => {
        if (!active || !target.current || !window.google?.accounts.id) return;
        window.google.accounts.id.initialize({
          client_id: clientId,
          auto_select: false,
          ux_mode: 'popup',
          callback: (response) => {
            if (active && response.credential) void callback.current(response.credential);
          },
        });
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
        if (active) setError(error instanceof Error ? error.message : 'เชื่อมต่อ Google ไม่ได้');
      });
    return () => {
      active = false;
      target.current?.replaceChildren();
    };
  }, [clientId, attempt]);
  return (
    <div className="google-sign-in">
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
      <small>หากปิดหน้าต่างเลือกบัญชี สามารถกดปุ่ม Google อีกครั้งได้</small>
    </div>
  );
}

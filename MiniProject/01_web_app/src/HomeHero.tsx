import type { FormEvent } from 'react';
import { Mascot } from './Forest';

export default function HomeHero({
  name,
  value,
  busy,
  change,
  submit,
  openLibrary,
  openChat,
}: {
  name: string;
  value: string;
  busy: boolean;
  change: (value: string) => void;
  submit: (event: FormEvent) => void;
  openLibrary: () => void;
  openChat: () => void;
}) {
  return (
    <section className="home-hero" aria-labelledby="home-title">
      <div className="home-story">
        <span className="forest-eyebrow">ยินดีต้อนรับกลับคุณ{name}</span>
        <h1 id="home-title">
          เปลี่ยนคลิป
          <br />
          ให้เป็นความรู้
          <span className="coral-stroke" />
        </h1>
        <p>
          ถาม สรุป และเรียนรู้
          <br className="mobile-only" /> พร้อมแหล่งอ้างอิงที่ตรวจสอบได้
        </p>
        <div className="hero-import-card">
          <form onSubmit={submit}>
            <label className="visually-hidden" htmlFor="home-urls">
              วางลิงก์ YouTube
            </label>
            <textarea
              id="home-urls"
              rows={2}
              value={value}
              onChange={(event) => change(event.target.value)}
              placeholder="วางลิงก์ YouTube ที่นี่…"
              disabled={busy}
            />
            <button className="primary" disabled={busy || !value.trim()}>
              {busy ? 'กำลังเพิ่ม…' : 'เพิ่มวิดีโอ'} <span aria-hidden="true">→</span>
            </button>
          </form>
          <div className="hero-shortcuts">
            <button onClick={openLibrary}>
              <span aria-hidden="true">▣</span> เปิดคลังวิดีโอ
            </button>
            <span className="shortcut-divider" />
            <button onClick={openChat}>
              <span aria-hidden="true">▤</span> เริ่มถามจากคลิป
            </button>
          </div>
        </div>
        <span className="home-small-note">
          บทถอดเสียงคือจุดเริ่มต้น · ทุกคำตอบเชื่อมกลับสู่คลิป
        </span>
      </div>
      <div className="home-mascot">
        <div className="mascot-halo" />
        <Mascot />
        <span className="buddy-speech">พร้อมเรียนรู้ด้วยกันไหม?</span>
      </div>
    </section>
  );
}

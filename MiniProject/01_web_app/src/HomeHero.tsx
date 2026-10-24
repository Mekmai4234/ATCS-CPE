import type { FormEvent } from 'react';
import { Mascot } from './Forest';
import { LearningScene, UiIcon } from './Visuals';

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
        <span className="forest-eyebrow">
          <UiIcon name="spark" size={16} /> YOUR PERSONAL LEARNING BUDDY
        </span>
        <h1 id="home-title">
          ดูน้อยลง
          <br />
          เข้าใจมากขึ้น
          <span className="coral-stroke" />
        </h1>
        <p>
          เปลี่ยนคลิปโปรดให้เป็นความรู้
          <br />
          ถาม สรุป และเรียนรู้ไปกับ Buddy
        </p>
        <div className="hero-import-card">
          <label className="hero-import-label" htmlFor="home-urls">
            <UiIcon name="link" /> เริ่มจากลิงก์ YouTube
          </label>
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
          <p className="hero-import-hint">นำเข้าแล้วถาม พร้อมอ้างอิงช่วงเวลาในคลิป</p>
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
        <span className="home-small-note">ยินดีต้อนรับคุณ{name} · เรียนรู้จากคลิปในคลังของคุณ</span>
      </div>
      <div className="home-mascot">
        <LearningScene />
        <div className="mascot-halo" />
        <Mascot />
        <span className="buddy-speech">ไปเรียนรู้กัน!</span>
      </div>
    </section>
  );
}

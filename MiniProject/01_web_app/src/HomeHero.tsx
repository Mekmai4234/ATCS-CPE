import type { FormEvent } from 'react';
import { BuddyArt } from './BuddyArt';
import { UiIcon } from './Visuals';
export default function HomeHero({
  value,
  busy,
  change,
  submit,
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
    <section className="home-hero v5-home-stage" aria-labelledby="home-title">
      <div className="v5-home-copy">
        <h1 id="home-title">
          รู้ให้<span>ลึกขึ้น.</span>
        </h1>
        <form className="v5-url-form" onSubmit={submit}>
          <label htmlFor="home-urls">ลิงก์ YouTube</label>
          <div>
            <input
              id="home-urls"
              type="url"
              value={value}
              onChange={(e) => change(e.target.value)}
              placeholder="วางลิงก์คลิปที่นี่"
              disabled={busy}
              required
            />
            <button
              className="primary"
              aria-label="เพิ่มคลิป (เพิ่มวิดีโอ)"
              disabled={busy || !value.trim()}
            >
              {busy ? 'กำลังเพิ่ม…' : 'เพิ่มคลิป'}
              <UiIcon name="arrow" />
            </button>
          </div>
        </form>
      </div>
      <div className="v5-home-art">
        <span className="v5-halo" aria-hidden="true" />
        <BuddyArt pose="home" />
      </div>
    </section>
  );
}

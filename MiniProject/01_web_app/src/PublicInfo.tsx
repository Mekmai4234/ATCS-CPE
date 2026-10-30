import { useState } from 'react';
import { BuddyLogo } from './Forest';
import { BuddyArt } from './BuddyArt';
import { UiIcon } from './Visuals';
import './secondary-v5.css';

export const isInfoPath = (path: string) => ['/privacy', '/terms', '/help'].includes(path);
export function InfoLinks() {
  return (
    <nav className="login-links" aria-label="ข้อมูลการใช้งาน">
      <a href="/terms">ข้อกำหนดการใช้งาน</a>
      <a href="/privacy">ความเป็นส่วนตัว</a>
      <a href="/help">ช่วยเหลือ</a>
    </nav>
  );
}
const privacySections = [
  [
    'ข้อมูลจาก Google',
    'Google ใช้เพื่อยืนยันตัวตน ระบบรับชื่อ อีเมล และรูปโปรไฟล์ตามที่ Google ส่งให้ ไม่ขอสิทธิ์อ่าน Gmail และไม่มีรหัสผ่านของเว็บ',
  ],
  [
    'ข้อมูลในบัญชี',
    'เซสชันใช้ cookie ของระบบ ข้อความ คลังคลิป งาน และสื่อเรียนรู้เชื่อมกับบัญชีของคุณ เว็บไม่บันทึก Google token หรือประวัติส่วนตัวใน localStorage โดยเก็บได้เฉพาะพิกัดปุ่ม Buddy ที่คุณย้าย',
  ],
  [
    'เมื่อส่งคำถาม',
    'คำถามถูกส่งพร้อมขอบเขตคลิปที่เลือกไปยังระบบประมวลผลของบริการ เพื่อสร้างคำตอบพร้อมแหล่งอ้างอิง',
  ],
  [
    'จัดการข้อมูล',
    'การนำคลิปออกจากคลังทำให้หลักฐานของคลิปนั้นใช้ไม่ได้ในบัญชีคุณ ประวัติคำตอบเดิมอาจยังคงอยู่ ติดต่อผู้ดูแลระบบที่ให้บัญชีหรือจัดการการติดตั้งนี้เมื่อต้องการจัดการข้อมูลเพิ่มเติม',
  ],
];
const termSections = [
  [
    'ใช้คลิปที่คุณเข้าถึงได้',
    'ใช้ Video Buddy กับคลิปที่คุณมีสิทธิ์เข้าถึง เลือกคลิปที่พร้อมก่อนถามคำถาม ระบบใช้หลักฐานจากขอบเขตนั้น ไม่ใช่แชตทั่วไปที่ไม่มีแหล่งข้อมูล',
  ],
  [
    'ตรวจสอบแหล่งอ้างอิง',
    'คำตอบอัตโนมัติอาจไม่ครบหรือคลาดเคลื่อน ควรเปิดแหล่งอ้างอิงและตรวจช่วงเวลาในคลิปก่อนนำไปใช้ การแสดงคำตอบบางส่วนหรือแหล่งข้อมูลใช้ไม่ได้เป็นข้อจำกัดที่ต้องพิจารณา',
  ],
  [
    'เริ่มงานเมื่อกดส่ง',
    'งานที่กดส่งอาจเรียกบริการประมวลผลตามการตั้งค่าของผู้ดูแล ไม่มีการเริ่มงานจาก suggestion เพียงเพราะเปิดแชต โหมด DEMO ใช้ข้อมูลจำลอง ไม่ใช่คำตอบจากคลิปจริง',
  ],
  [
    'ดูแลบัญชีของคุณ',
    'ออกจากระบบเมื่อใช้เครื่องร่วมกัน หากออกจากระบบไม่สำเร็จ ให้กดลองออกจากระบบอีกครั้งก่อนสลับบัญชี ประวัติที่บันทึกไว้ยังเปิดได้เมื่อเข้าสู่บัญชีเดิม',
  ],
];
const helpSections = [
  [
    'เพิ่มวิดีโออย่างไร?',
    'วางลิงก์ YouTube ในหน้าวิดีโอของฉัน แล้วกดเพิ่ม รอจนพร้อมใช้งานก่อนเลือกคลิป',
  ],
  [
    'ถาม Buddy จากตรงไหน?',
    'เลือกคลิปในคลังหรือใน Buddy แล้วพิมพ์คำถาม Enter เพื่อส่ง และ Shift+Enter เพื่อขึ้นบรรทัดใหม่ เปลี่ยนชุดคลิปแล้วคำถามถัดไปจะเริ่มบทสนทนาใหม่',
  ],
  [
    'เข้าสู่ระบบไม่ได้?',
    'ใช้หน้าเข้าสู่ระบบเดียว บัญชีใหม่สร้างเป็นสมาชิกทั่วไปอัตโนมัติ หากปิดหน้าต่างหรือ browser บล็อก popup ให้กด Google อีกครั้งและอนุญาต popup สำหรับเว็บนี้ หากแจ้งว่ายังไม่ตั้งค่า ให้ติดต่อผู้ดูแลระบบ',
  ],
  [
    'กลับมาอ่านและถามต่ออย่างไร?',
    'เปิดเมนูประวัติแชทเพื่อค้นหาบทสนทนาเดิม เลือกรายการเพื่ออ่านย้อนหลัง และกดถามต่อในบทสนทนานี้เมื่อพร้อมส่งคำถามใหม่',
  ],
  [
    'ย้ายหรือย่อ Buddy ได้ไหม?',
    'ลากปุ่มวงกลมไปยังตำแหน่งที่ต้องการ หรือกด Tab ไปที่ปุ่ม Buddy แล้วใช้ปุ่มลูกศรเพื่อย้าย กด Home เพื่อกลับมุมขวาล่าง และ Enter เพื่อเปิดหรือย่อแชต เมื่อย่อแล้วสามารถเปิดกลับได้โดยไม่เริ่มบทสนทนาใหม่',
  ],
  [
    'ออกจากระบบแล้วข้อมูลหายไหม?',
    'การออกจากระบบปิดข้อมูลส่วนตัวบนหน้าจอ ประวัติที่บันทึกไว้ยังเปิดได้เมื่อเข้าสู่บัญชีเดิม หากออกจากระบบไม่สำเร็จ ให้กดลองออกจากระบบอีกครั้งก่อนสลับบัญชี',
  ],
];

export default function PublicInfo({ path }: { path: string }) {
  const [search, setSearch] = useState('');
  const kind = path === '/privacy' ? 'privacy' : path === '/terms' ? 'terms' : 'help';
  const sections =
    kind === 'privacy' ? privacySections : kind === 'terms' ? termSections : helpSections;
  const filtered =
    kind === 'help'
      ? sections.filter(([title, copy]) => `${title} ${copy}`.includes(search.trim()))
      : sections;
  return (
    <div className={`vb-public vb-public-${kind}`}>
      <header className="vb-public-header">
        <BuddyLogo />
        <nav aria-label="ข้อมูลเว็บไซต์">
          <a href="/help" aria-current={kind === 'help' ? 'page' : undefined}>
            ช่วยเหลือ
          </a>
          <a href="/privacy" aria-current={kind === 'privacy' ? 'page' : undefined}>
            ข้อมูลส่วนตัว
          </a>
          <a href="/terms" aria-current={kind === 'terms' ? 'page' : undefined}>
            ข้อกำหนด
          </a>
        </nav>
        <a className="vb-secondary-link" href="/login">
          เข้าสู่ระบบ <UiIcon name="arrow" />
        </a>
      </header>
      <main className="vb-public-main">
        <section className="vb-public-hero">
          <div className="vb-public-copy">
            <h1
              aria-label={
                kind === 'privacy'
                  ? 'ความเป็นส่วนตัว'
                  : kind === 'terms'
                    ? 'ข้อกำหนดการใช้งาน'
                    : 'ช่วยเหลือ Video Buddy'
              }
            >
              {kind === 'privacy' ? (
                <>
                  ข้อมูล<span>ของคุณ</span>
                </>
              ) : kind === 'terms' ? (
                'ข้อตกลง'
              ) : (
                'ช่วยเหลือ'
              )}
            </h1>
            {kind === 'help' && (
              <div className="vb-public-search">
                <label className="visually-hidden" htmlFor="help-search">
                  ค้นหาคำถาม
                </label>
                <UiIcon name="help" />
                <input
                  id="help-search"
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="ค้นหาคำถาม"
                />
              </div>
            )}
            {kind === 'privacy' && (
              <p className="vb-trust-line">
                <UiIcon name="link" /> ไม่ขอสิทธิ์อ่าน Gmail
              </p>
            )}
            {kind === 'terms' && (
              <a className="vb-inline-link" href="/privacy">
                ความเป็นส่วนตัว <UiIcon name="arrow" />
              </a>
            )}
          </div>
          <div className="vb-public-art">
            <BuddyArt pose={kind} />
          </div>
        </section>
        <section
          className="vb-public-detail-section"
          aria-label={kind === 'help' ? 'คำถามที่พบบ่อย' : 'รายละเอียด'}
        >
          {kind !== 'terms' && <h2>{kind === 'help' ? 'คำถามที่พบบ่อย' : 'ความเป็นส่วนตัว'}</h2>}
          <div className="vb-public-details">
            {!filtered.length && <p role="status">ไม่พบคำถาม ลองค้นหาด้วยคำอื่น</p>}
            {filtered.map(([title, copy], i) => (
              <details className="vb-disclosure" key={title} open={search.trim() ? true : i === 0}>
                <summary>
                  {title}
                  <span aria-hidden="true">+</span>
                </summary>
                <p>{copy}</p>
              </details>
            ))}
          </div>
        </section>
      </main>
      <footer className="vb-public-footer">
        <span>Video Buddy</span>
        <a href="/login">
          กลับหน้าเข้าสู่ระบบ <UiIcon name="arrow" />
        </a>
      </footer>
    </div>
  );
}

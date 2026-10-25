export type IconName =
  'home' | 'library' | 'chat' | 'learn' | 'link' | 'spark' | 'quiz' | 'arrow' | 'clock' | 'help';
export function UiIcon({ name, size = 22 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, string> = {
    home: 'm3 10 9-7 9 7v10h-6v-7H9v7H3z',
    library: 'M5 3h12l3 3v15H5z M9 8h6 M9 12h7 M9 16h7',
    chat: 'M4 4h16v13H9l-5 4z M8 9h1 m3 0h1 m3 0h1',
    learn: 'm2 8 10-5 10 5-10 5z M5 12v5l7 4 7-4v-5',
    link: 'm10 13 4-4 M8 15l-2 2a3.5 3.5 0 0 1-5-5l5-5a3.5 3.5 0 0 1 5 0 M13 9l2-2a3.5 3.5 0 0 1 5 5l-5 5a3.5 3.5 0 0 1-5 0',
    spark: 'm12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3z',
    quiz: 'M8 3H5v18h14V3h-3 M9 2h6v4H9z M10 10a2 2 0 1 1 3 2v2 M12 17h.01',
    arrow: 'M4 12h16 m-6-6 6 6-6 6',
    clock: 'M3 5v5h5 M3 10a9 9 0 1 1 1 8 M12 7v5l3 2',
    help: 'M9 8a3 3 0 1 1 5 2c-2 1-2 2-2 3 M12 17h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}

export function LoginBenefits() {
  return (
    <ul className="login-benefits">
      <li>
        <UiIcon name="chat" />
        <span>ถามตอบจากวิดีโอของคุณ</span>
      </li>
      <li>
        <UiIcon name="library" />
        <span>ดูแหล่งอ้างอิงพร้อมช่วงเวลา</span>
      </li>
      <li>
        <UiIcon name="clock" />
        <span>เก็บประวัติการเรียนรู้ไว้ในบัญชี</span>
      </li>
    </ul>
  );
}

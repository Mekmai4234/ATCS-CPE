export function ForestBackdrop() {
  return (
    <picture className="forest-backdrop" aria-hidden="true">
      <source media="(max-width: 720px)" srcSet="/assets/forest-mobile.webp" />
      <img src="/assets/forest-desktop.webp" alt="" fetchPriority="high" />
    </picture>
  );
}
export function Mascot({ className = '' }: { className?: string }) {
  return (
    <img
      className={`mascot-3d ${className}`}
      src="/assets/rag-buddy-640.webp"
      srcSet="/assets/rag-buddy-320.webp 320w, /assets/rag-buddy-640.webp 640w, /assets/rag-buddy-1200.webp 1200w"
      sizes="(max-width: 720px) 260px, 460px"
      width="640"
      height="640"
      alt="RAG Buddy มาสคอตสีมิ้นต์ใส่หูฟังโบกมือต้อนรับ"
    />
  );
}
export function BuddyLogo({ onClick }: { onClick?: () => void }) {
  return (
    <a
      className="buddy-logo"
      href="/"
      onClick={
        onClick
          ? (event) => {
              event.preventDefault();
              onClick();
            }
          : undefined
      }
    >
      <span aria-hidden="true">▶</span>
      <span>
        RAG BUDDY<small>YOUTUBE KNOWLEDGE</small>
      </span>
    </a>
  );
}

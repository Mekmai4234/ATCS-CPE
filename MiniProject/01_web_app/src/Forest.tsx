import InteractiveBuddy from './InteractiveBuddy';
export function ForestBackdrop() {
  return <div className="mint-backdrop" aria-hidden="true" />;
}
export function Mascot({ className = '' }: { className?: string }) {
  return <InteractiveBuddy className={`mascot-3d ${className}`} />;
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

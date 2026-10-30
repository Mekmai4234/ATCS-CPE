const poses = new Set([
  'home',
  'library',
  'learning',
  'history',
  'summary',
  'compare',
  'research',
  'quiz',
  'flashcards',
  'study-plan',
  'chat',
  'buddy',
  'admin',
  'members',
  'help',
  'privacy',
  'terms',
  'empty-library',
  'states',
]);

/** Approved v5 artwork. Decorative: the adjacent heading explains the page. */
export function BuddyArt({ pose, className = '' }: { pose: string; className?: string }) {
  const name = pose.replaceAll('_', '-');
  return (
    <img
      className={`buddy-art ${className}`}
      src={`/buddy-v5/${poses.has(name) ? name : 'home'}.webp`}
      alt=""
      width={1024}
      height={1024}
      decoding="async"
      draggable={false}
    />
  );
}

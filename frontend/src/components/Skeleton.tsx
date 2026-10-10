/** Placeholder blocks while results load (skeletons, not just a spinner). */
export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="animate-pulse space-y-3 rounded-xl border border-sand bg-surface p-4" aria-hidden="true">
      <div className="h-5 w-1/3 rounded bg-sand" />
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className={`h-4 rounded bg-sand/70 ${i === lines - 1 ? "w-2/3" : "w-full"}`} />
      ))}
    </div>
  );
}

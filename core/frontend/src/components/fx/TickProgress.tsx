/** Progress as a graduated ruler: one segment per item, done segments amber,
 *  the next one pulsing. Past `maxTicks` items the ruler shows proportions. */
export function TickProgress({
  done,
  total,
  maxTicks = 48,
  className = "",
}: {
  done: number;
  total: number;
  maxTicks?: number;
  className?: string;
}) {
  if (total <= 0) return null;
  const ticks = Math.min(total, maxTicks);
  const lit = Math.round((done / total) * ticks);
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={done}
      aria-label={`${done} of ${total} done`}
      className={`fx-ticks ${className}`}
    >
      {Array.from({ length: ticks }, (_, i) => (
        <span key={i} className="fx-tick" data-lit={i < lit || undefined} data-next={i === lit || undefined} />
      ))}
    </div>
  );
}

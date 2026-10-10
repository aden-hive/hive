import { useEffect, useState } from "react";
import { useFullMotion } from "@/lib/motion";

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

/** One odometer column: a 0–9 strip translated to the current digit. It mounts
 *  on 0 and rolls to its value, so a fresh counter "boots" into place. */
function DigitColumn({ digit }: { digit: number }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setShown(digit));
    return () => cancelAnimationFrame(frame);
  }, [digit]);
  return (
    <span className="fx-roll-col">
      <span className="fx-roll-strip" style={{ transform: `translateY(${-shown}lh)` }}>
        {DIGITS.map((d) => (
          <span key={d}>{d}</span>
        ))}
      </span>
    </span>
  );
}

/** An integer whose digits roll to each new value. The plain value stays in
 *  the DOM for assistive tech and copy; the columns are decorative. */
export function RollingNumber({ value, className = "" }: { value: number; className?: string }) {
  const full = useFullMotion();
  const text = String(value);
  if (!full) return <span className={`tabular-nums ${className}`}>{text}</span>;
  const chars = [...text];
  return (
    <span className={`tabular-nums ${className}`}>
      <span className="sr-only">{text}</span>
      <span aria-hidden className="fx-roll">
        {chars.map((ch, i) => {
          // Key from the right so the units column keeps its identity (and
          // rolls instead of remounting) when the number gains a digit.
          const key = chars.length - i;
          return /\d/.test(ch) ? <DigitColumn key={key} digit={Number(ch)} /> : <span key={key}>{ch}</span>;
        })}
      </span>
    </span>
  );
}

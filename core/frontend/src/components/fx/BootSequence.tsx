import { useEffect, useState } from "react";
import HiveLogo from "@/components/HiveLogo";
import { ScrambleText } from "./ScrambleText";
import { isFullMotion } from "@/lib/motion";

const SEEN_KEY = "hive-boot-seen";
const LINES = ["HIVE RUNTIME", "QUEEN NETWORK", "COLONY BUS"];
const TOTAL_MS = 1500;
const DECODE_MS = 380;

function alreadyBooted(): boolean {
  try {
    return sessionStorage.getItem(SEEN_KEY) === "1";
  } catch {
    return true;
  }
}

/** A once-per-tab boot card: the honeycomb draws itself while the subsystems
 *  report in, then the card dissolves. Click-through from the first frame and
 *  skipped entirely under reduced motion. */
export default function BootSequence() {
  const [visible, setVisible] = useState(() => isFullMotion() && !alreadyBooted());

  useEffect(() => {
    if (!visible) return;
    try {
      sessionStorage.setItem(SEEN_KEY, "1");
    } catch {
      // Private mode: the card just plays again next load.
    }
    const done = window.setTimeout(() => setVisible(false), TOTAL_MS);
    return () => window.clearTimeout(done);
  }, [visible]);

  if (!visible) return null;
  return (
    <div aria-hidden className="fx-boot">
      <div className="fx-boot-card">
        <HiveLogo size={56} className="fx-boot-logo text-primary" />
        <div className="fx-boot-lines font-mono">
          {LINES.map((line, i) => {
            const start = 180 + i * 170;
            return (
              <div key={line} className="fx-boot-line" style={{ animationDelay: `${start}ms` }}>
                <ScrambleText text={line} delayMs={start} durationMs={DECODE_MS} />
                <span className="fx-boot-leader" />
                {/* Reports in once its line has decoded. */}
                <span className="fx-boot-ok text-primary" style={{ animationDelay: `${start + DECODE_MS}ms` }}>
                  OK
                </span>
              </div>
            );
          })}
          <div className="fx-boot-bar" />
        </div>
      </div>
    </div>
  );
}

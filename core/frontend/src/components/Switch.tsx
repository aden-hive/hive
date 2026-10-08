/**
 * Standard on/off switch — the app's canonical toggle. Wraps a visually
 * hidden checkbox (so it stays keyboard- and a11y-friendly) with the shared
 * peer-styled track + knob used across Settings, Sentinel, etc.
 *
 *   <Switch checked={on} onChange={setOn} />
 *   <Switch checked={on} onChange={setOn} disabled={!ready} />
 */
export function Switch({
  checked,
  onChange,
  disabled,
  className = "",
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  /** Extra classes for the wrapping label (positioning only). */
  className?: string;
}) {
  return (
    <label
      className={`relative inline-flex items-center cursor-pointer flex-shrink-0 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-40 ${className}`}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="sr-only peer"
      />
      <div className="w-9 h-5 bg-muted border border-border/60 rounded-full peer peer-checked:bg-primary peer-checked:border-primary/60 transition-colors after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-background after:border after:border-border/60 after:rounded-full after:h-4 after:w-4 after:transition-transform peer-checked:after:translate-x-4" />
    </label>
  );
}

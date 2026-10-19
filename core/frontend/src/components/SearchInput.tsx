import { Search, X, Loader2 } from "lucide-react";
import type { ChangeEvent, InputHTMLAttributes } from "react";

interface SearchInputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** Set false to hide the clear (X) button when value is non-empty. */
  clearable?: boolean;
  /** Swap the leading search icon for a spinner (e.g. while a query settles). */
  loading?: boolean;
}

/**
 * Unified search input used across the app (Credentials, Prompt Library,
 * Skills Library, etc.). Single style: muted surface, leading search icon,
 * trailing clear button when there's a query. Pages that need extra width
 * control wrap this in a sized container.
 */
export function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
  clearable = true,
  loading = false,
  className = "",
  ...rest
}: SearchInputProps) {
  return (
    <div className={`relative ${className}`}>
      {loading ? (
        <Loader2 className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/70 animate-spin" />
      ) : (
        <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
      )}
      <input
        type="text"
        value={value}
        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full h-9 pl-9 pr-8 rounded-lg border border-border/60 bg-muted/30 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:border-primary/40 focus:ring-1 focus:ring-primary/30 focus:bg-background transition-colors"
        {...rest}
      />
      {clearable && value && (
        <button
          type="button"
          onClick={() => onChange("")}
          className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-md text-muted-foreground/60 hover:text-foreground hover:bg-muted/60 transition-colors"
          aria-label="Clear search"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}

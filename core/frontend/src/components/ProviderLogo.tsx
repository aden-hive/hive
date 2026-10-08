import { getProviderLogo } from "@/data/providerLogos";

function isLightHex(hex: string): boolean {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return false;
  const r = parseInt(m[1].slice(0, 2), 16);
  const g = parseInt(m[1].slice(2, 4), 16);
  const b = parseInt(m[1].slice(4, 6), 16);
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.7;
}

export function ProviderLogo({
  provider,
  size = 20,
  className,
}: {
  provider: string;
  size?: number;
  className?: string;
}) {
  const logo = getProviderLogo(provider);
  if (!logo) return null;
  if (logo.s) {
    return (
      <img
        src={`./logos/${logo.s}`}
        width={size}
        height={size}
        alt={logo.name ?? provider}
        loading="lazy"
        decoding="async"
        style={{ objectFit: "contain", display: "inline-block" }}
        className={className}
      />
    );
  }
  if (logo.d) {
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        fill={logo.c}
        role="img"
        className={className}
      >
        <path d={logo.d} />
      </svg>
    );
  }
  if (logo.m) {
    const text = isLightHex(logo.c) ? "#111827" : "#ffffff";
    return (
      <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        role="img"
        aria-label={logo.name}
        className={className}
      >
        <rect width="24" height="24" rx="5" fill={logo.c} />
        <text
          x="12"
          y="17"
          textAnchor="middle"
          fontSize="13"
          fontWeight="700"
          fontFamily="system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
          fill={text}
        >
          {logo.m}
        </text>
      </svg>
    );
  }
  return null;
}

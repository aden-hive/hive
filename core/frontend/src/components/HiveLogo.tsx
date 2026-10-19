/** OpenHive honeycomb logo — 7 hexagons in a flower pattern. */
export default function HiveLogo({
  size = 20,
  className = "",
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinejoin="round"
      width={size}
      height={size}
      className={className}
    >
      <g transform="translate(32,32) scale(1.15) translate(-32,-27)">
        <polygon points="20,14 25.2,17 25.2,23 20,26 14.8,23 14.8,17" />
        <polygon points="32,7 37.2,10 37.2,16 32,19 26.8,16 26.8,10" />
        <polygon points="44,14 49.2,17 49.2,23 44,26 38.8,23 38.8,17" />
        <polygon points="44,28 49.2,31 49.2,37 44,40 38.8,37 38.8,31" />
        <polygon points="32,35 37.2,38 37.2,44 32,47 26.8,44 26.8,38" />
        <polygon points="20,28 25.2,31 25.2,37 20,40 14.8,37 14.8,31" />
        <polygon points="32,21 37.2,24 37.2,30 32,33 26.8,30 26.8,24" />
      </g>
    </svg>
  );
}

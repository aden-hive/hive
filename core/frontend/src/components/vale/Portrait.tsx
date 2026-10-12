import { useId } from "react";

/** How a villager is drawn: stories/<story>/art.toml, [people.<id>]. */
export interface PersonArt {
  skin?: string;
  hair?: string;
  style?: "short" | "long" | "bun" | "braids" | "wild" | "receding" | "slick" | "none";
  beard?: "none" | "stubble" | "full" | "long" | "goatee";
  hat?: "none" | "cap" | "scarf" | "circlet" | "miner" | "wimple" | "hat" | "merchant" | "hood";
  coat?: string;
  trim?: string;
  age?: "young" | "adult" | "old";
  extras?: string[];
  /** A painted picture under the story's art/ folder, used instead of the drawing. */
  image?: string;
}

const INK = "#2b2420";

function shade(hex: string, f: number): string {
  const n = hex.replace("#", "");
  const c = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16));
  const out = c.map((x) => Math.max(0, Math.min(255, Math.round(f < 0 ? x * (1 + f) : x + (255 - x) * f))));
  return "#" + out.map((x) => x.toString(16).padStart(2, "0")).join("");
}

function HairBack({ a }: { a: PersonArt }) {
  const hair = a.hair ?? "#5a4030";
  switch (a.style) {
    case "long":
      return <path d="M18.5 31 C17 13 47 13 45.5 31 L47 52 C43 54 40.5 49 40 42 L24 42 C23.5 49 21 54 17 52 Z" fill={hair} />;
    case "braids":
      return (
        <g fill={hair}>
          <path d="M19.5 30 C18 14 46 14 44.5 30 Z" />
          {[0, 1, 2, 3].map((i) => <ellipse key={`l${i}`} cx={20.5 - i * 0.4} cy={37 + i * 4.6} rx={2.6} ry={2.8} />)}
          {[0, 1, 2, 3].map((i) => <ellipse key={`r${i}`} cx={43.5 + i * 0.4} cy={37 + i * 4.6} rx={2.6} ry={2.8} />)}
          <circle cx={19} cy={54.5} r={1.4} fill={shade(hair, 0.35)} />
          <circle cx={45} cy={54.5} r={1.4} fill={shade(hair, 0.35)} />
        </g>
      );
    case "wild":
      return (
        <g fill={hair}>
          {[[19, 24, 6], [24, 16.5, 6.5], [32, 14, 7], [40, 16.5, 6.5], [45, 24, 6], [17.5, 33, 5], [46.5, 33, 5], [18.5, 41, 4], [45.5, 41, 4]].map(([x, y, r], i) => (
            <circle key={i} cx={x} cy={y} r={r} />
          ))}
        </g>
      );
    case "bun":
      return <circle cx={32} cy={13.5} r={5.2} fill={hair} />;
    default:
      return null;
  }
}

function HairTop({ a }: { a: PersonArt }) {
  const hair = a.hair ?? "#5a4030";
  switch (a.style) {
    case "short":
    case "long":
    case "braids":
    case "bun":
    case "wild":
      return <path d="M20.3 30 C19.5 17.5 25.5 15 32 15 C38.5 15 44.5 17.5 43.7 30 C42.5 24.5 39 21.5 32 21.5 C26 21.5 21.8 24 20.3 30 Z" fill={hair} />;
    case "slick":
      return (
        <g>
          <path d="M20.3 29 C19.5 17 25 14.6 32 14.6 C39 14.6 44.5 17 43.7 29 C43 22.5 39.5 20.2 34 20.2 L27 21.4 C23.5 22.2 21.2 24.8 20.3 29 Z" fill={hair} />
          <path d="M33 16.2 C37 16.4 40.5 18.2 41.6 21" stroke={shade(hair, 0.45)} strokeWidth={0.7} fill="none" strokeLinecap="round" />
        </g>
      );
    case "receding":
      return (
        <g fill={hair}>
          <path d="M20.4 32 C20.2 26.5 21.3 23.4 23.6 21.8 L24.2 30 C22.6 30.4 21.4 31.1 20.4 32 Z" />
          <path d="M43.6 32 C43.8 26.5 42.7 23.4 40.4 21.8 L39.8 30 C41.4 30.4 42.6 31.1 43.6 32 Z" />
        </g>
      );
    default:
      return null;
  }
}

function Beard({ a }: { a: PersonArt }) {
  const hair = a.hair ?? "#5a4030";
  switch (a.beard) {
    case "stubble":
      return <path d="M21.5 33 C22 42 26.5 45.6 32 45.6 C37.5 45.6 42 42 42.5 33 C40.5 38.5 37 40 32 40 C27 40 23.5 38.5 21.5 33 Z" fill={hair} opacity={0.32} />;
    case "full":
      return (
        <g fill={hair}>
          <path d="M20.8 31.5 C20.6 44 25.8 48.6 32 48.6 C38.2 48.6 43.4 44 43.2 31.5 C41.2 37.5 37.5 39.6 32 39.6 C26.5 39.6 22.8 37.5 20.8 31.5 Z" />
          <path d="M27 37.6 C29 36.2 35 36.2 37 37.6 C35 39 29 39 27 37.6 Z" />
        </g>
      );
    case "long":
      return (
        <g fill={hair}>
          <path d="M21 32 C20.5 47 25 57 32 58.5 C39 57 43.5 47 43 32 C41 38 37.5 40 32 40 C26.5 40 23 38 21 32 Z" />
          <path d="M26.5 37.4 C29 35.8 35 35.8 37.5 37.4 C35 39 29 39 26.5 37.4 Z" />
        </g>
      );
    case "goatee":
      return (
        <g fill={hair}>
          <path d="M28.5 37.4 C30 36.4 34 36.4 35.5 37.4 C34 38.2 30 38.2 28.5 37.4 Z" />
          <path d="M29.8 41.2 C30.4 45.6 33.6 45.6 34.2 41.2 Z" />
        </g>
      );
    default:
      return null;
  }
}

function Hat({ a }: { a: PersonArt }) {
  const coat = a.coat ?? "#777";
  const trim = a.trim ?? "#ddd";
  switch (a.hat) {
    case "cap":
      return (
        <g>
          <path d="M19.2 25.5 C19 15 45 15 44.8 25.5 Z" fill={shade(trim, -0.25)} />
          <path d="M18.5 25 C26 23.4 38 23.4 47.5 25.6 C46.5 27.6 42 27.8 41 27.4 L20 27.2 C19 26.8 18.4 26 18.5 25 Z" fill={shade(trim, -0.38)} />
        </g>
      );
    case "scarf":
      return <path d="M18.8 33 C17 14 47 14 45.2 33 C44 28 43.4 22.6 32 22 C20.6 22.6 20 28 18.8 33 Z" fill={coat} />;
    case "circlet":
      return (
        <g>
          <path d="M20.8 23.6 C26 21.2 38 21.2 43.2 23.6" stroke={trim} strokeWidth={1.5} fill="none" />
          <circle cx={32} cy={21.4} r={1.4} fill="#c23b3b" stroke={trim} strokeWidth={0.5} />
        </g>
      );
    case "miner":
      return (
        <g>
          <path d="M18.6 25.2 C18.6 11.8 45.4 11.8 45.4 25.2 Z" fill="#b89a52" />
          <rect x={17} y={24.2} width={30} height={2.6} rx={1.3} fill="#9b8040" />
          <circle cx={32} cy={18.6} r={2.6} fill="#ffe08a" stroke="#6b5a2a" strokeWidth={0.6} />
        </g>
      );
    case "wimple":
      return (
        <g>
          <path d="M17 64 L17 30 C17 11 47 11 47 30 L47 64 Z" fill={coat} />
          <path d="M20.6 44 C19.6 34 20 17.8 32 17.8 C44 17.8 44.4 34 43.4 44 C40.5 48.5 23.5 48.5 20.6 44 Z" fill={trim} />
        </g>
      );
    case "hat":
      return (
        <g>
          <ellipse cx={32} cy={23.6} rx={18} ry={3.6} fill={shade(trim, -0.1)} />
          <path d="M23 23.6 C23 13.6 41 13.6 41 23.6 Z" fill={trim} />
          <rect x={23.2} y={20.4} width={17.6} height={1.8} fill={shade(trim, -0.45)} />
        </g>
      );
    case "merchant":
      return (
        <g>
          <path d="M19.4 24.4 C17 12 33 9 44.6 17.5 C46.6 19.4 45.6 23.6 44.6 24.4 Z" fill={trim} />
          <path d="M19 24.6 C26 22.6 38 22.6 45 24.6 L45 26.4 C38 25 26 25 19 26.4 Z" fill={shade(trim, -0.3)} />
          <path d="M42 17 C47 11.5 51 11.5 52 12.5 C49.5 13.5 46.5 15.5 44 18.6 Z" fill="#c8a24a" />
        </g>
      );
    case "hood":
      return (
        <g>
          <path d="M14 64 L15.5 34 C15 12 49 12 48.5 34 L50 64 Z" fill={coat} />
          <path d="M20.2 40 C19.2 27 22 19.6 32 19.6 C42 19.6 44.8 27 43.8 40 C40 46 24 46 20.2 40 Z" fill={shade(coat, -0.45)} />
        </g>
      );
    default:
      return null;
  }
}

/** A villager's portrait, drawn into a 64 by 64 box. Use inside any SVG. */
export function PortraitArt({ art, health = 0, bg }: { art: PersonArt; health?: number; bg: string }) {
  const skin = health >= 2 ? shade(art.skin ?? "#e8c3a0", 0.28) : (art.skin ?? "#e8c3a0");
  const coat = art.coat ?? "#777";
  const trim = art.trim ?? "#ddd";
  const extras = new Set(art.extras ?? []);
  const hooded = art.hat === "hood" || art.hat === "wimple";
  const young = art.age === "young";
  const old = art.age === "old";
  const eyeY = 30.6;
  return (
    <g>
      <rect width={64} height={64} fill={bg} />
      <circle cx={32} cy={30} r={26} fill="#ffffff" opacity={0.18} />
      {art.hat === "hood" || art.hat === "wimple" ? <Hat a={art} /> : null}
      <HairBack a={art} />
      {/* shoulders */}
      <path d="M4 64 C5 52 14 47 24 45.6 L40 45.6 C50 47 59 52 60 64 Z" fill={coat} />
      {extras.has("fur") && <path d="M12 52 C18 46 25 46.5 32 47.5 C39 46.5 46 46 52 52 C46 51 40 52.6 32 52.6 C24 52.6 18 51 12 52 Z" fill={trim} />}
      {extras.has("maid") && <path d="M22 46 L32 53 L42 46 C40 50.5 36.5 54 32 54.5 C27.5 54 24 50.5 22 46 Z" fill={trim} />}
      {extras.has("apron") && <path d="M24.5 50 L39.5 50 L41 64 L23 64 Z M24.5 50 L22 46.6 M39.5 50 L42 46.6" fill={trim} stroke={trim} strokeWidth={1.2} />}
      {extras.has("bow") && (
        <g>
          <path d="M10 60 C8 44 20 34 30 33" stroke="#7a5a32" strokeWidth={1.6} fill="none" />
          <path d="M14 64 L50 46" stroke="#5a4428" strokeWidth={2} />
        </g>
      )}
      {!hooded && art.hat !== "scarf" && <path d="M26 45.6 L32 52 L38 45.6" fill="none" stroke={trim} strokeWidth={1.6} strokeLinejoin="round" />}
      {/* neck and head */}
      <rect x={27.5} y={38} width={9} height={9} rx={3} fill={shade(skin, -0.08)} />
      {!hooded && <ellipse cx={20.3} cy={31.5} rx={2} ry={3} fill={shade(skin, -0.06)} />}
      {!hooded && <ellipse cx={43.7} cy={31.5} rx={2} ry={3} fill={shade(skin, -0.06)} />}
      <ellipse cx={32} cy={30} rx={young ? 11.2 : 11.6} ry={young ? 12.8 : 13.6} fill={skin} />
      <HairTop a={art} />
      {extras.has("fox") && (
        <g>
          <path d="M20 22 L18.4 8.6 L28.4 16.6 Z" fill={art.hair ?? "#eee"} />
          <path d="M21 19.6 L20.2 12 L25.8 16.6 Z" fill="#f4b6c6" />
          <path d="M44 22 L45.6 8.6 L35.6 16.6 Z" fill={art.hair ?? "#eee"} />
          <path d="M43 19.6 L43.8 12 L38.2 16.6 Z" fill="#f4b6c6" />
        </g>
      )}
      {extras.has("maid") && <path d="M21.5 20.5 C26 17 38 17 42.5 20.5 L42 22.4 C37.5 19.6 26.5 19.6 22 22.4 Z" fill={trim} />}
      {/* face */}
      {health >= 2 ? (
        <g stroke={INK} strokeWidth={0.9} strokeLinecap="round">
          <path d={`M26 ${eyeY} q1.6 1 3.2 0`} fill="none" />
          <path d={`M34.8 ${eyeY} q1.6 1 3.2 0`} fill="none" />
        </g>
      ) : (
        <g fill={INK}>
          <ellipse cx={27.6} cy={eyeY} rx={young ? 1.35 : 1.15} ry={young ? 1.55 : 1.3} />
          <ellipse cx={36.4} cy={eyeY} rx={young ? 1.35 : 1.15} ry={young ? 1.55 : 1.3} />
          {young && <circle cx={28.1} cy={eyeY - 0.5} r={0.4} fill="#fff" />}
          {young && <circle cx={36.9} cy={eyeY - 0.5} r={0.4} fill="#fff" />}
        </g>
      )}
      <path d={`M25.4 ${eyeY - 3.4} q2.2 -1.1 4.4 0 M34.2 ${eyeY - 3.4} q2.2 -1.1 4.4 0`} stroke={art.style === "none" || !art.hair ? INK : shade(art.hair, -0.25)} strokeWidth={0.9} fill="none" strokeLinecap="round" />
      <path d="M32 32.4 q-0.9 2.6 0.4 3.2" stroke={shade(skin, -0.25)} strokeWidth={0.8} fill="none" strokeLinecap="round" />
      {art.beard !== "full" && art.beard !== "long" && (
        <path d={health >= 1 ? "M29 39.2 q3 -1.2 6 0" : "M29 38.6 q3 1.8 6 0"} stroke={health >= 1 ? "#9a3b3b" : shade(skin, -0.4)} strokeWidth={1} fill="none" strokeLinecap="round" />
      )}
      {young && <circle cx={25} cy={35} r={1.8} fill="#e8818a" opacity={0.28} />}
      {young && <circle cx={39} cy={35} r={1.8} fill="#e8818a" opacity={0.28} />}
      {old && <path d="M23.6 31.8 l-1.6 0.9 M40.4 31.8 l1.6 0.9 M28 24.6 q4 -1 8 0" stroke={shade(skin, -0.3)} strokeWidth={0.6} fill="none" strokeLinecap="round" />}
      <Beard a={art} />
      {art.hat !== "hood" && art.hat !== "wimple" && <Hat a={art} />}
      {extras.has("quill") && <path d="M44 33 C48 24 52 16 55 12 C53 18 50 25 45.4 33.6 Z" fill="#f2efe6" stroke="#b9b2a2" strokeWidth={0.4} />}
      {extras.has("herbs") && (
        <g fill="#6f9a4a">
          <path d="M47 52 L52 42" stroke="#557a36" strokeWidth={0.8} />
          <ellipse cx={50.6} cy={44.4} rx={1.6} ry={0.8} transform="rotate(-50 50.6 44.4)" />
          <ellipse cx={49.2} cy={47.4} rx={1.6} ry={0.8} transform="rotate(30 49.2 47.4)" />
          <circle cx={52} cy={42} r={1} fill="#f4f1ea" />
        </g>
      )}
      {extras.has("flour") && (
        <g fill="#fffaf0" opacity={0.85}>
          <circle cx={25} cy={49} r={0.6} /><circle cx={38} cy={51} r={0.5} /><circle cx={44} cy={55} r={0.6} /><circle cx={21} cy={56} r={0.5} />
          <circle cx={36} cy={44} r={0.4} />
        </g>
      )}
      {health >= 2 && <path d="M43 22 q1.2 2 0 3 q-1.2 -1 0 -3 Z" fill="#9fd3e6" />}
    </g>
  );
}

/** A villager's portrait as a round token. Falls back to their initial when the story draws nobody. */
export default function Portrait({
  art, color, name, size = 32, health = 0, ring, imageBase, className,
}: {
  art?: PersonArt; color: string; name: string; size?: number; health?: number; ring?: string; imageBase?: string; className?: string;
}) {
  const id = useId().replace(/:/g, "");
  const bg = color + "33";
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={className} role="img" aria-label={name}>
      <defs>
        <clipPath id={`pc${id}`}><circle cx={32} cy={32} r={31} /></clipPath>
      </defs>
      <g clipPath={`url(#pc${id})`}>
        {art?.image && imageBase ? (
          <image href={`${imageBase}/${art.image}`} width={64} height={64} preserveAspectRatio="xMidYMid slice" />
        ) : art ? (
          <PortraitArt art={art} health={health} bg={bg} />
        ) : (
          <g>
            <rect width={64} height={64} fill={color} />
            <text x={32} y={41} textAnchor="middle" fontSize={26} fill="#fff" fontWeight={600}>{name.slice(0, 1)}</text>
          </g>
        )}
      </g>
      <circle cx={32} cy={32} r={31} fill="none" stroke={ring ?? color} strokeWidth={ring ? 3 : 2} />
    </svg>
  );
}

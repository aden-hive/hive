import { useId } from "react";
import { PortraitArt, type PersonArt } from "./Portrait";

/** How a place is drawn: stories/<story>/art.toml, [places.<id>]. */
export interface PlaceArt {
  kind?: "mine" | "keep" | "mill" | "village" | "chapel" | "stones" | "pasture" | "forest" | "ford" | "vale";
  water?: boolean;
  image?: string;
}

export interface SceneFigure {
  id: string;
  name: string;
  color: string;
  art?: PersonArt;
  health?: number;
}

export interface SceneState {
  hour: number; // 0 dawn … 5 night
  weather?: string; // rain, fog, clear, overcast, showers, wind
  winter?: boolean;
  blight?: number; // of this place's water, 0..1
  shaftOpen?: boolean;
  stoneRaised?: boolean;
  ullrAwake?: boolean;
  hum?: boolean;
}

const SKY: [string, string][] = [
  ["#f0b99c", "#fbe6cc"], // dawn
  ["#9ccbe8", "#e4f1f5"], // morning
  ["#86bfe6", "#d9edfb"], // midday
  ["#a5c4dc", "#f1e2c0"], // afternoon
  ["#7d63a3", "#f19d66"], // dusk
  ["#111a31", "#26365a"], // night
];
const SUN: [number, number][] = [[24, 52], [44, 24], [80, 13], [116, 26], [136, 54], [122, 16]];
const SHADE: [string, number][] = [["#ff9a5a", 0.1], ["#ffffff", 0], ["#ffffff", 0], ["#ffb347", 0.07], ["#7a3fa0", 0.18], ["#0b1430", 0.5]];

function mix(a: string, b: string, t: number): string {
  const pa = a.match(/\w\w/g)!.map((h) => parseInt(h, 16));
  const pb = b.match(/\w\w/g)!.map((h) => parseInt(h, 16));
  return "#" + pa.map((x, i) => Math.round(x + (pb[i] - x) * t).toString(16).padStart(2, "0")).join("");
}

const waterColor = (blight: number) => mix("4a7d97", "a8352c", Math.min(1, blight / 0.7));

function Window({ x, y, w = 3, h = 3.4, lit }: { x: number; y: number; w?: number; h?: number; lit: boolean }) {
  if (!lit) return <rect x={x} y={y} width={w} height={h} rx={0.6} fill="#3b3a3f" opacity={0.55} />;
  // Lit windows are drawn again above the dusk and the night (see SceneArt), so they glow through them.
  return (
    <g style={{ visibility: "visible" }}>
      <rect x={x - 1.2} y={y - 1.2} width={w + 2.4} height={h + 2.4} rx={1.6} fill="#ffcf6a" opacity={0.28} />
      <rect x={x} y={y} width={w} height={h} rx={0.6} fill="#ffd98a" />
    </g>
  );
}

/** The middle of the picture: what makes this place itself. */
function Place({ kind, s, lit }: { kind: string; s: SceneState; lit: boolean }) {
  const stone = "#cfc6b8";
  const roof = "#8a5a3a";
  const water = waterColor(s.blight ?? 0);
  switch (kind) {
    case "mine":
      return (
        <g>
          <path d="M70 70 L104 22 L124 34 L160 18 L160 70 Z" fill="#8d8374" />
          <path d="M104 22 L114 36 L124 34 Z" fill="#a39a8a" />
          <path d="M98 70 C98 56 104 50 112 50 C120 50 126 56 126 70 Z" fill="#241e1b" />
          {s.shaftOpen && <ellipse cx={112} cy={64} rx={9} ry={6} fill="#c0392b" opacity={0.55}><animate attributeName="opacity" values="0.35;0.7;0.35" dur="3s" repeatCount="indefinite" /></ellipse>}
          <path d="M96 70 L96 52 L128 52 L128 70" stroke="#6b4a2b" strokeWidth={2.4} fill="none" />
          <path d="M94 51.4 L130 51.4" stroke="#6b4a2b" strokeWidth={3} />
          <path d="M30 70 C40 58 52 58 62 70 Z" fill="#9b958c" />
          <path d="M74 74 L132 74" stroke="#5c4a3a" strokeWidth={0.8} />
          <rect x={80} y={66} width={12} height={6} rx={1} fill="#6b5a4a" />
          <circle cx={83} cy={73} r={1.6} fill="#3b2f26" /><circle cx={89} cy={73} r={1.6} fill="#3b2f26" />
          <path d="M112 70 C104 76 86 78 60 80 C40 81.5 20 84 0 86" stroke={water} strokeWidth={3} fill="none" strokeLinecap="round" />
        </g>
      );
    case "keep":
      return (
        <g>
          <path d="M40 72 C60 52 100 48 130 72 Z" fill="#7d8a6a" />
          <rect x={62} y={34} width={36} height={22} fill={stone} />
          {[62, 68, 74, 80, 86, 92].map((x) => <rect key={x} x={x} y={31} width={3.4} height={3.4} fill={stone} />)}
          <rect x={52} y={24} width={12} height={32} fill={mix("cfc6b8", "8a8170", 0.15)} />
          <rect x={96} y={26} width={12} height={30} fill={mix("cfc6b8", "8a8170", 0.15)} />
          <path d="M50 24 L58 14 L66 24 Z M94 26 L102 16 L110 26 Z" fill="#5a3f6e" />
          <path d="M58 14 L58 8 L64 10 L58 12" fill="#7a4b9c" stroke="#5a3f6e" strokeWidth={0.4} />
          <path d="M74 56 L74 46 C74 42 86 42 86 46 L86 56 Z" fill="#3b2f26" />
          <path d="M77 41 C79 38 81 38 83 41" stroke="#4f7a3a" strokeWidth={0.9} fill="none" />
          <Window x={56} y={32} lit={lit} /><Window x={100} y={34} lit={lit} /><Window x={67} y={40} w={2.6} lit={lit} /><Window x={91} y={40} w={2.6} lit={lit} />
        </g>
      );
    case "mill":
      return (
        <g>
          <rect x={54} y={40} width={38} height={28} fill="#d8c3a0" />
          <path d="M50 41 L73 24 L96 41 Z" fill={roof} />
          <rect x={64} y={54} width={8} height={14} fill="#5a3f2a" />
          <Window x={80} y={47} w={5} h={5} lit={lit} /><Window x={58} y={46} w={4} h={4} lit={lit} />
          <path d="M0 76 C30 72 60 74 96 72 C120 71 140 74 160 72 L160 80 C130 82 100 80 70 82 C40 84 20 82 0 84 Z" fill={water} opacity={0.9} />
          <g transform="translate(106 58)">
            <g>
              <animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="18s" repeatCount="indefinite" />
              <circle r={15} fill="none" stroke="#6b4a2b" strokeWidth={2.2} />
              {[0, 30, 60, 90, 120, 150].map((a) => <line key={a} x1={-15} y1={0} x2={15} y2={0} stroke="#6b4a2b" strokeWidth={1.3} transform={`rotate(${a})`} />)}
              {Array.from({ length: 12 }, (_, i) => <rect key={i} x={13} y={-2} width={4.5} height={4} fill="#7d5a3a" transform={`rotate(${i * 30})`} />)}
            </g>
            <circle r={2.6} fill="#4a3424" />
          </g>
        </g>
      );
    case "village":
      return (
        <g>
          {[[18, 48, 26], [48, 44, 30], [84, 47, 26], [116, 43, 30]].map(([x, y, w], i) => (
            <g key={i}>
              <rect x={x} y={y} width={w} height={70 - y} fill={i === 2 ? "#e3d2b2" : "#ddc9a6"} />
              <path d={`M${x - 3} ${y + 1} L${x + w / 2} ${y - 13} L${x + w + 3} ${y + 1} Z`} fill={i % 2 ? "#b5964e" : "#a58a46"} />
              <Window x={x + 5} y={y + 7} lit={lit} /><Window x={x + w - 8} y={y + 7} lit={lit} />
              <rect x={x + w / 2 - 2.5} y={64} width={5} height={6} fill="#5a3f2a" />
            </g>
          ))}
          <rect x={137} y={24} width={3} height={10} fill="#7a6a5a" />
          <path d="M139 22 C141 16 137 12 140 6" stroke="#cfcfcf" strokeWidth={2} fill="none" opacity={0.5} />
          <g transform="translate(76 70)">
            <ellipse cx={0} cy={4} rx={7} ry={2.4} fill="#6f6a62" />
            <rect x={-6} y={-2} width={12} height={6} fill={stone} />
            <ellipse cx={0} cy={-2} rx={6} ry={1.8} fill={water} />
            <path d="M-6 -2 L-6 -10 M6 -2 L6 -10 M-8 -10 L8 -10" stroke="#6b4a2b" strokeWidth={1.2} />
          </g>
          <g transform="translate(104 38)">
            <path d="M0 0 L0 6" stroke="#4a3a2a" strokeWidth={0.6} />
            <rect x={-2.2} y={6} width={4.4} height={5} rx={1} fill={lit ? "#ffd27a" : "#c8a24a"} />
          </g>
        </g>
      );
    case "chapel":
      return (
        <g>
          <rect x={56} y={36} width={48} height={34} fill={stone} />
          <path d="M52 37 L80 20 L108 37 Z" fill="#6f6a72" />
          <rect x={98} y={14} width={14} height={56} fill={mix("cfc6b8", "8a8170", 0.12)} />
          <path d="M96 15 L105 4 L114 15 Z" fill="#6f6a72" />
          <path d="M105 4 L105 -1 M102.6 1.2 L107.4 1.2" stroke="#6f6a72" strokeWidth={1} />
          <circle cx={80} cy={45} r={5.5} fill={lit ? "#ffd27a" : "#3b4a6a"} />
          {!lit && <g opacity={0.9}><path d="M80 39.5 L80 50.5 M74.5 45 L85.5 45" stroke="#c8a24a" strokeWidth={0.6} /><circle cx={77.5} cy={42.5} r={1.4} fill="#a8352c" /><circle cx={82.5} cy={47.5} r={1.4} fill="#5a8f4a" /></g>}
          <path d="M74 70 L74 58 C74 53 86 53 86 58 L86 70 Z" fill="#4a3424" />
          <Window x={103} y={26} w={4} h={6} lit={lit} />
          <path d="M20 76 L44 73 L58 77 L80 74" stroke="#2b2420" strokeWidth={0.7} fill="none" opacity={0.6} />
          {[24, 34, 140, 150].map((x) => <path key={x} d={`M${x} 70 L${x} 64 C${x} 61 ${x + 5} 61 ${x + 5} 64 L${x + 5} 70 Z`} fill="#a9a196" />)}
        </g>
      );
    case "stones": {
      const glow = s.ullrAwake ? "#1d7a74" : s.hum ? "#6d9f9b" : null;
      return (
        <g>
          <path d="M10 72 C40 30 120 30 150 72 Z" fill="#8fa07a" />
          <path d="M60 52 C66 42 94 42 100 52 Z" fill="#7f9068" />
          {glow && <ellipse cx={80} cy={50} rx={46} ry={14} fill="none" stroke={glow} strokeWidth={1} strokeDasharray="2 1.5" opacity={0.85}><animate attributeName="opacity" values="0.4;0.9;0.4" dur="4s" repeatCount="indefinite" /></ellipse>}
          {Array.from({ length: 7 }, (_, i) => {
            const a = Math.PI * (0.12 + (0.76 * i) / 6);
            const x = 80 - Math.cos(a) * 42;
            const y = 56 - Math.sin(a) * 12;
            const down = i === 3 && !s.stoneRaised;
            return down
              ? <rect key={i} x={x - 6} y={y + 1} width={12} height={4} rx={1.2} fill="#7d7a72" transform={`rotate(8 ${x} ${y})`} />
              : <rect key={i} x={x - 2.6} y={y - 11} width={5.2} height={13} rx={1.4} fill={glow ? mix("8d8a82", glow.slice(1), 0.25) : "#8d8a82"} />;
          })}
          {s.ullrAwake && <g fill="#ffffff" opacity={0.7}>{[30, 50, 70, 90, 110, 130].map((x) => <circle key={x} cx={x} cy={58 + (x % 3)} r={0.8} />)}</g>}
        </g>
      );
    }
    case "pasture":
      return (
        <g>
          <path d="M0 62 C40 50 110 50 160 60 L160 90 L0 90 Z" fill="#9aaa72" />
          <rect x={112} y={42} width={22} height={18} fill="#cdb894" />
          <path d="M108 43 L123 32 L138 43 Z" fill="#7a5a3a" />
          <Window x={118} y={48} lit={lit} />
          <path d="M14 68 L96 66 M14 62 L96 60" stroke="#7a5a3a" strokeWidth={1.1} />
          {[14, 30, 46, 62, 78, 96].map((x) => <rect key={x} x={x - 0.8} y={58} width={1.6} height={11} fill="#6b4a2b" />)}
          {[[30, 72], [44, 75], [58, 71], [72, 76], [86, 73]].map(([x, y], i) => (
            <g key={i}>
              <ellipse cx={x} cy={y} rx={4.4} ry={2.8} fill="#f1ede2" />
              <ellipse cx={x + 4.2} cy={y - 0.8} rx={1.6} ry={1.4} fill="#3b3430" />
            </g>
          ))}
          <ellipse cx={146} cy={66} rx={7} ry={2.2} fill={waterColor(s.blight ?? 0)} />
        </g>
      );
    case "forest":
      return (
        <g>
          {Array.from({ length: 14 }, (_, i) => {
            const x = 6 + i * 11.5 + (i % 2) * 3;
            const h = 26 + ((i * 7) % 11);
            const c = ["#4f6a3a", "#5d7a40", "#7a7a38", "#8a6a2e"][i % 4];
            return (
              <g key={i}>
                <rect x={x - 1} y={70 - 8} width={2} height={8} fill="#4a3424" />
                <path d={`M${x - 8} ${66} L${x} ${66 - h} L${x + 8} ${66} Z`} fill={c} />
              </g>
            );
          })}
          <path d="M0 80 C30 74 60 78 90 75 C120 72 140 77 160 75 L160 84 C120 86 90 82 60 85 C30 87 10 84 0 86 Z" fill={waterColor(s.blight ?? 0)} opacity={0.85} />
          <rect x={24} y={58} width={14} height={10} fill="#a0805a" />
          <path d="M22 59 L31 51 L40 59 Z" fill="#6b4a2b" />
          <Window x={28} y={61} w={2.6} h={2.8} lit={lit} />
        </g>
      );
    case "ford":
      return (
        <g>
          <path d="M0 70 C40 66 80 68 120 66 C140 65 150 66 160 65 L160 80 C120 82 80 80 40 82 C20 83 10 82 0 82 Z" fill={waterColor(s.blight ?? 0)} />
          {[[16, "#a8352c"], [44, "#3f7d6e"], [72, "#c8a24a"]].map(([x, c], i) => (
            <g key={i}>
              <rect x={Number(x)} y={52} width={22} height={12} fill="#cdb894" />
              <path d={`M${Number(x) - 2} 52 L${Number(x) + 24} 52 L${Number(x) + 22} 46 L${Number(x)} 46 Z`} fill={String(c)} />
              <path d={`M${Number(x) + 4} 46 L${Number(x) + 2} 52 M${Number(x) + 11} 46 L${Number(x) + 11} 52 M${Number(x) + 18} 46 L${Number(x) + 20} 52`} stroke="#f4f1ea" strokeWidth={1.4} opacity={0.6} />
            </g>
          ))}
          <path d="M108 72 L148 72 L144 77 L112 77 Z" fill="#6b4a2b" />
          <rect x={124} y={60} width={1.4} height={12} fill="#5a3f2a" />
          <path d="M126 61 L138 69 L126 69 Z" fill="#e8e0cc" />
        </g>
      );
    default: // the whole vale, for openings
      return (
        <g>
          <path d="M0 60 C30 44 60 50 90 44 C120 38 140 46 160 42 L160 90 L0 90 Z" fill="#93a675" />
          <path d="M0 74 C40 68 70 74 100 70 C130 66 150 70 160 68" stroke={waterColor(s.blight ?? 0)} strokeWidth={2.6} fill="none" />
          {[[60, 54], [70, 56], [78, 53]].map(([x, y], i) => (
            <g key={i}><rect x={x} y={y} width={6} height={5} fill="#ddc9a6" /><path d={`M${x - 1} ${y} L${x + 3} ${y - 4} L${x + 7} ${y} Z`} fill="#a58a46" /></g>
          ))}
          <g transform="translate(120 34)"><rect x={0} y={0} width={10} height={7} fill={stone} /><rect x={-2} y={-3} width={3} height={10} fill={stone} /><rect x={9} y={-3} width={3} height={10} fill={stone} /></g>
          <g transform="translate(30 42)">{[0, 3, 6, 9, 12].map((x) => <rect key={x} x={x} y={x === 6 && !s.stoneRaised ? 3 : 0} width={1.6} height={x === 6 && !s.stoneRaised ? 1.4 : 4} fill="#7d7a72" />)}</g>
        </g>
      );
  }
}

function Weather({ kind, winter, id }: { kind?: string; winter?: boolean; id: string }) {
  if (winter) {
    return (
      <g fill="#ffffff">
        {Array.from({ length: 40 }, (_, i) => (
          <circle key={i} cx={(i * 37) % 160} cy={(i * 23) % 90} r={0.7 + (i % 3) * 0.25} opacity={0.85}>
            <animate attributeName="cy" values={`${(i * 23) % 90 - 90};${(i * 23) % 90 + 0.1}`} dur={`${6 + (i % 5)}s`} repeatCount="indefinite" />
          </circle>
        ))}
        <path d="M0 86 C40 83 80 85 120 83 C140 82 150 84 160 83 L160 90 L0 90 Z" opacity={0.9} />
      </g>
    );
  }
  if (kind === "rain" || kind === "showers") {
    const n = kind === "rain" ? 46 : 20;
    return (
      <g>
        {kind === "showers" && (
          <g opacity={0.35} fill="none" strokeWidth={1.4}>
            {["#e05a5a", "#e8a33a", "#e8d53a", "#5ab05a", "#4a8ad0", "#7a5ab0"].map((c, i) => <path key={c} d={`M20 ${70 + i * 1.4} C40 ${10 + i * 1.4} 120 ${10 + i * 1.4} 140 ${70 + i * 1.4}`} stroke={c} />)}
          </g>
        )}
        <g stroke="#dbe7f0" strokeWidth={0.5} opacity={0.6}>
          <animateTransform attributeName="transform" type="translate" values="0 -10; -4 10" dur="0.7s" repeatCount="indefinite" />
          {Array.from({ length: n }, (_, i) => {
            const x = (i * 53) % 170;
            const y = (i * 29) % 100 - 5;
            return <line key={i} x1={x} y1={y} x2={x - 2} y2={y + 6} />;
          })}
        </g>
      </g>
    );
  }
  if (kind === "fog") {
    return (
      <g fill="#f4f4f2">
        <defs><filter id={`fog${id}`}><feGaussianBlur stdDeviation="2.2" /></filter></defs>
        <g filter={`url(#fog${id})`} opacity={0.55}>
          <ellipse cx={40} cy={66} rx={60} ry={6} /><ellipse cx={120} cy={60} rx={60} ry={5} /><ellipse cx={80} cy={76} rx={90} ry={6} />
        </g>
      </g>
    );
  }
  if (kind === "wind") {
    return (
      <g stroke="#ffffff" strokeWidth={0.7} fill="none" opacity={0.6} strokeLinecap="round">
        <animateTransform attributeName="transform" type="translate" values="-20 0; 20 0" dur="3s" repeatCount="indefinite" />
        <path d="M10 20 C30 16 50 24 70 18" /><path d="M60 34 C80 30 100 38 120 32" /><path d="M20 46 C35 43 45 49 60 45" />
        <g fill="#c8862e" stroke="none"><ellipse cx={40} cy={30} rx={1.4} ry={0.7} /><ellipse cx={110} cy={24} rx={1.4} ry={0.7} /></g>
      </g>
    );
  }
  return null;
}

/** A picture of a place at this hour, in this weather, with the people who are there. */
export default function SceneArt({
  place, s, people = [], label, imageBase, className,
}: {
  place?: PlaceArt; s: SceneState; people?: SceneFigure[]; label?: string; imageBase?: string; className?: string;
}) {
  const id = useId().replace(/:/g, "");
  const hour = Math.max(0, Math.min(5, s.hour));
  const grey = s.weather === "overcast" || s.weather === "rain" || s.weather === "fog" ? 0.45 : s.weather === "showers" ? 0.2 : 0;
  const [top, bottom] = SKY[hour].map((c) => mix(c.slice(1), "9aa3a8", hour === 5 ? grey * 0.3 : grey));
  const night = hour === 5;
  const lit = hour >= 4;
  const [sx, sy] = SUN[hour];
  const kind = place?.kind ?? "vale";
  const shown = people.slice(0, 7);
  const ground = night ? "#26303a" : hour === 4 ? "#8f8a5a" : "#a3a364";
  return (
    <svg viewBox="0 0 160 90" className={className} role="img" aria-label={label} preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id={`sky${id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={top} /><stop offset="1" stopColor={bottom} /></linearGradient>
        <radialGradient id={`sun${id}`}><stop offset="0" stopColor={night ? "#f6f0d8" : "#fff4c8"} /><stop offset="1" stopColor={night ? "#f6f0d8" : "#ffd27a"} stopOpacity={0} /></radialGradient>
      </defs>
      {place?.image && imageBase ? (
        <image href={`${imageBase}/${place.image}`} width={160} height={90} preserveAspectRatio="xMidYMid slice" />
      ) : (
        <g>
          <rect width={160} height={90} fill={`url(#sky${id})`} />
          {night && <g fill="#fff">{Array.from({ length: 26 }, (_, i) => <circle key={i} cx={(i * 47) % 160} cy={(i * 13) % 40} r={i % 4 ? 0.35 : 0.6} opacity={0.8} />)}</g>}
          {grey < 0.4 && <circle cx={sx} cy={sy} r={night ? 9 : 14} fill={`url(#sun${id})`} />}
          {grey < 0.4 && <circle cx={sx} cy={sy} r={night ? 3.6 : 4.4} fill={night ? "#f3ecd2" : "#fff1c2"} />}
          {grey > 0 && <g fill="#e6e8ea" opacity={night ? 0.15 : 0.6}><ellipse cx={30} cy={14} rx={30} ry={5} /><ellipse cx={110} cy={10} rx={40} ry={6} /><ellipse cx={80} cy={22} rx={36} ry={4} /></g>}
          <path d="M0 52 C25 40 45 46 70 38 C95 30 120 40 160 34 L160 90 L0 90 Z" fill={night ? "#2c3a4a" : mix("b9c9b4", "9aa3a8", grey * 0.5)} />
          <path d="M0 60 C30 50 60 56 90 50 C120 44 140 52 160 48 L160 90 L0 90 Z" fill={night ? "#25323e" : mix("9db59a", "8e9a90", grey * 0.5)} />
          <rect y={68} width={160} height={22} fill={ground} />
          <Place kind={kind} s={s} lit={lit} />
          <rect width={160} height={90} fill={SHADE[hour][0]} opacity={SHADE[hour][1]} style={{ mixBlendMode: night ? "multiply" : "soft-light" }} />
          {lit && <g style={{ visibility: "hidden" }} aria-hidden><Place kind={kind} s={s} lit={lit} /></g>}
          <Weather kind={s.weather} winter={s.winter} id={id} />
        </g>
      )}
      {shown.map((p, i) => {
        const size = 15;
        const x = 80 - (shown.length * (size + 2)) / 2 + i * (size + 2);
        return (
          <g key={p.id}>
            <ellipse cx={x + size / 2} cy={59.5} rx={size / 2.2} ry={1.3} fill="#000" opacity={0.25} />
            <svg x={x} y={44} width={size} height={size} viewBox="0 0 64 64">
              <defs><clipPath id={`f${id}${i}`}><circle cx={32} cy={32} r={31} /></clipPath></defs>
              <g clipPath={`url(#f${id}${i})`}>
                {p.art ? <PortraitArt art={p.art} health={p.health} bg={p.color + "55"} /> : <rect width={64} height={64} fill={p.color} />}
              </g>
              <circle cx={32} cy={32} r={31} fill="none" stroke="#fff" strokeWidth={3} />
            </svg>
          </g>
        );
      })}
    </svg>
  );
}

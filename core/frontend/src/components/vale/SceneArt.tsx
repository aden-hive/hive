import { useId } from "react";
import { PortraitArt, type PersonArt } from "./Portrait";

/** How a place is drawn: stories/<story>/art.toml, [places.<id>]. */
export interface PlaceArt {
  kind?:
    | "mine" | "keep" | "mill" | "village" | "chapel" | "stones" | "pasture" | "forest" | "ford"
    | "lighthouse" | "harbor" | "orchard" | "garden" | "cave"
    | "vale" | "isle";
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

/** What the picture shows of the world now; the world's rules decide the numbers (rules.toml [scene]). */
export interface SceneState {
  hour: number; // 0 dawn … 5 night
  weather?: string; // rain, fog, clear, overcast, showers, wind
  winter?: boolean;
  water?: number; // how troubled this place's water is, 0..1
  glow?: number; // how brightly this place glows (a lit lamp, lanterns strung), 0..1
  marks?: Record<string, unknown>; // the world's own marks: deep_door, stone_raised, awake, hum, ebb …
}

const mark = (s: SceneState, name: string) => Boolean(s.marks?.[name]);

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

/** Little waves on open water. */
function Waves({ y }: { y: number }) {
  return (
    <g stroke="#ffffff" strokeWidth={0.45} fill="none" opacity={0.55}>
      <animateTransform attributeName="transform" type="translate" values="0 0; 3 0; 0 0" dur="5s" repeatCount="indefinite" />
      {Array.from({ length: 9 }, (_, i) => <path key={i} d={`M${(i * 19) % 160} ${y + (i % 3) * 3} q2 -1.2 4 0 q2 -1.2 4 0`} />)}
    </g>
  );
}

/** A string of festival lanterns, more of them the brighter the place glows. */
function Lanterns({ from, to, n }: { from: [number, number]; to: [number, number]; n: number }) {
  const [x1, y1] = from;
  const [x2, y2] = to;
  const sag = 6;
  return (
    <g style={{ visibility: "visible" }}>
      <path d={`M${x1} ${y1} Q${(x1 + x2) / 2} ${(y1 + y2) / 2 + sag} ${x2} ${y2}`} stroke="#4a3a2a" strokeWidth={0.4} fill="none" />
      {Array.from({ length: n }, (_, i) => {
        const t = (i + 0.5) / n;
        const x = x1 + (x2 - x1) * t;
        const y = (1 - t) * (1 - t) * y1 + 2 * (1 - t) * t * ((y1 + y2) / 2 + sag) + t * t * y2;
        return (
          <g key={i}>
            <circle cx={x} cy={y + 2.2} r={2.6} fill="#ffcf6a" opacity={0.25} />
            <ellipse cx={x} cy={y + 2.2} rx={1.3} ry={1.7} fill={["#e8553e", "#f2a13a", "#f6d04a"][i % 3]} />
          </g>
        );
      })}
    </g>
  );
}

/** The middle of the picture: what makes this place itself. */
function Place({ kind, s, lit }: { kind: string; s: SceneState; lit: boolean }) {
  const stone = "#cfc6b8";
  const roof = "#8a5a3a";
  const water = waterColor(s.water ?? 0);
  switch (kind) {
    case "mine":
      return (
        <g>
          <path d="M70 70 L104 22 L124 34 L160 18 L160 70 Z" fill="#8d8374" />
          <path d="M104 22 L114 36 L124 34 Z" fill="#a39a8a" />
          <path d="M98 70 C98 56 104 50 112 50 C120 50 126 56 126 70 Z" fill="#241e1b" />
          {mark(s, "deep_door") && <ellipse cx={112} cy={64} rx={9} ry={6} fill="#c0392b" opacity={0.55}><animate attributeName="opacity" values="0.35;0.7;0.35" dur="3s" repeatCount="indefinite" /></ellipse>}
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
          {(s.glow ?? 0) > 0.05 && <Lanterns from={[10, 40]} to={[150, 36]} n={Math.round(4 + 14 * (s.glow ?? 0))} />}
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
      const glow = mark(s, "awake") ? "#1d7a74" : mark(s, "hum") ? "#6d9f9b" : null;
      return (
        <g>
          <path d="M10 72 C40 30 120 30 150 72 Z" fill="#8fa07a" />
          <path d="M60 52 C66 42 94 42 100 52 Z" fill="#7f9068" />
          {glow && <ellipse cx={80} cy={50} rx={46} ry={14} fill="none" stroke={glow} strokeWidth={1} strokeDasharray="2 1.5" opacity={0.85}><animate attributeName="opacity" values="0.4;0.9;0.4" dur="4s" repeatCount="indefinite" /></ellipse>}
          {Array.from({ length: 7 }, (_, i) => {
            const a = Math.PI * (0.12 + (0.76 * i) / 6);
            const x = 80 - Math.cos(a) * 42;
            const y = 56 - Math.sin(a) * 12;
            const down = i === 3 && !mark(s, "stone_raised");
            return down
              ? <rect key={i} x={x - 6} y={y + 1} width={12} height={4} rx={1.2} fill="#7d7a72" transform={`rotate(8 ${x} ${y})`} />
              : <rect key={i} x={x - 2.6} y={y - 11} width={5.2} height={13} rx={1.4} fill={glow ? mix("8d8a82", glow.slice(1), 0.25) : "#8d8a82"} />;
          })}
          {mark(s, "awake") && <g fill="#ffffff" opacity={0.7}>{[30, 50, 70, 90, 110, 130].map((x) => <circle key={x} cx={x} cy={58 + (x % 3)} r={0.8} />)}</g>}
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
          <ellipse cx={146} cy={66} rx={7} ry={2.2} fill={waterColor(s.water ?? 0)} />
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
          <path d="M0 80 C30 74 60 78 90 75 C120 72 140 77 160 75 L160 84 C120 86 90 82 60 85 C30 87 10 84 0 86 Z" fill={waterColor(s.water ?? 0)} opacity={0.85} />
          <rect x={24} y={58} width={14} height={10} fill="#a0805a" />
          <path d="M22 59 L31 51 L40 59 Z" fill="#6b4a2b" />
          <Window x={28} y={61} w={2.6} h={2.8} lit={lit} />
        </g>
      );
    case "ford":
      return (
        <g>
          <path d="M0 70 C40 66 80 68 120 66 C140 65 150 66 160 65 L160 80 C120 82 80 80 40 82 C20 83 10 82 0 82 Z" fill={waterColor(s.water ?? 0)} />
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
    case "lighthouse": {
      const lit = (s.glow ?? 0) > 0.5;
      return (
        <g>
          <path d="M0 74 C30 70 60 74 90 72 L90 90 L0 90 Z" fill="#5f8fae" />
          <path d="M70 74 C80 52 100 46 160 44 L160 90 L64 90 Z" fill="#8f8a7a" />
          <path d="M84 70 C92 60 110 56 160 54 L160 60 C120 62 100 64 90 72 Z" fill="#7d9a6a" opacity={0.8} />
          <g transform="translate(118 18)">
            <path d="M-6 40 L-4 6 L4 6 L6 40 Z" fill="#f2efe6" />
            {[12, 22, 32].map((y) => <path key={y} d={`M${-4.6 + (y - 6) * 0.06} ${y} L${4.6 - (y - 6) * 0.06} ${y} L${4.9 - (y - 6) * 0.06} ${y + 4} L${-4.9 + (y - 6) * 0.06} ${y + 4} Z`} fill="#c0453a" />)}
            <rect x={-5} y={2} width={10} height={4} fill="#3b3a3f" />
            <rect x={-3.6} y={-3} width={7.2} height={5} rx={0.6} fill={lit ? "#ffe9a8" : "#5d6b78"} />
            <path d="M-4.6 -3 L0 -7.5 L4.6 -3 Z" fill="#2f3a44" />
            {lit && <circle r={9} cy={-0.5} fill="#ffe28a" opacity={0.35} style={{ visibility: "visible" }} />}
            {lit && (
              <g style={{ visibility: "visible" }} opacity={0.55}>
                <path d="M-2 -1 L-120 -16 L-120 12 Z" fill="url(#beam)">
                  <animateTransform attributeName="transform" type="rotate" values="-8 0 -1; 6 0 -1; -8 0 -1" dur="7s" repeatCount="indefinite" />
                </path>
              </g>
            )}
          </g>
          <Waves y={80} />
        </g>
      );
    }
    case "harbor":
      return (
        <g>
          <path d="M0 62 C40 60 80 64 160 60 L160 90 L0 90 Z" fill={waterColor(s.water ?? 0)} opacity={0.95} />
          <Waves y={70} />
          {[[14, 44, 30], [48, 46, 26], [124, 44, 30]].map(([x, y, w], i) => (
            <g key={i}>
              <rect x={x} y={y} width={w} height={60 - y} fill={i === 1 ? "#e6d9bf" : "#dccdb0"} />
              <path d={`M${x - 2} ${y + 1} L${x + w / 2} ${y - 9} L${x + w + 2} ${y + 1} Z`} fill={i % 2 ? "#4e7a8c" : "#8a5a3a"} />
              <Window x={x + 4} y={y + 5} lit={lit} /><Window x={x + w - 7} y={y + 5} lit={lit} />
            </g>
          ))}
          <path d="M84 60 L84 66 M84 62 L118 62 M118 60 L118 66 M96 62 L96 66 M108 62 L108 66" stroke="#6b4a2b" strokeWidth={1.4} />
          <rect x={82} y={59} width={38} height={2.2} fill="#8a6a46" />
          {[[60, 70, 1], [96, 72, -1], [134, 69, 1]].map(([x, y, dir], i) => (
            <g key={i} transform={`translate(${x} ${y})`}>
              <path d="M-8 0 L8 0 L5 3.4 L-5 3.4 Z" fill={["#8a5a3a", "#3f6f7e", "#b06a3a"][i]} />
              <rect x={-0.3} y={-9} width={0.6} height={9} fill="#4a3424" />
              <path d={`M0.6 -8.6 L${6 * dir} -1.4 L0.6 -1.4 Z`} fill="#f2ead8" />
            </g>
          ))}
          {(s.glow ?? 0) > 0.05 && <Lanterns from={[10, 40]} to={[150, 38]} n={Math.round(4 + 14 * (s.glow ?? 0))} />}
          <g stroke="#ffffff" strokeWidth={0.5} fill="none" opacity={0.8}>
            <path d="M30 22 q2 -1.6 4 0 q2 -1.6 4 0" /><path d="M100 16 q1.6 -1.2 3.2 0 q1.6 -1.2 3.2 0" />
          </g>
        </g>
      );
    case "orchard":
      return (
        <g>
          <path d="M0 70 C30 46 90 34 160 40 L160 90 L0 90 Z" fill="#8fae6a" />
          {[56, 62, 68].map((y) => <path key={y} d={`M0 ${y + 12} C40 ${y} 100 ${y - 10} 160 ${y - 8}`} stroke="#6f8e4e" strokeWidth={0.8} fill="none" opacity={0.6} />)}
          {Array.from({ length: 12 }, (_, i) => {
            const x = 12 + (i % 6) * 26 + (Math.floor(i / 6) ? 12 : 0);
            const y = Math.floor(i / 6) ? 62 : 50 + (i % 6) * -1.6;
            return (
              <g key={i}>
                <rect x={x - 0.8} y={y} width={1.6} height={6} fill="#5a3f2a" />
                <circle cx={x} cy={y - 2} r={5} fill={i % 3 ? "#5f8a3e" : "#6e9a48"} />
                {[[-2, -3], [2, -1], [0, 1], [3, -4]].map(([dx, dy], j) => <circle key={j} cx={x + dx} cy={y - 2 + dy} r={0.9} fill="#d8423a" />)}
              </g>
            );
          })}
          <rect x={128} y={30} width={18} height={12} fill="#e2cfa8" />
          <path d="M125 31 L137 23 L149 31 Z" fill="#8a5a3a" />
          <Window x={132} y={34} lit={lit} />
          {(s.glow ?? 0) > 0.05 && <Lanterns from={[8, 46]} to={[120, 34]} n={Math.round(3 + 10 * (s.glow ?? 0))} />}
        </g>
      );
    case "garden":
      return (
        <g>
          <path d="M0 62 C40 56 100 58 160 54 L160 90 L0 90 Z" fill="#9ab86e" />
          {Array.from({ length: 40 }, (_, i) => (
            <circle key={i} cx={(i * 37) % 160} cy={62 + ((i * 13) % 22)} r={0.9} fill={["#f2c14e", "#e8829a", "#ffffff", "#b07ad8"][i % 4]} />
          ))}
          {[[24, 56], [40, 58], [56, 55], [72, 57]].map(([x, y], i) => (
            <g key={i}>
              <rect x={x} y={y} width={8} height={9} fill="#e8d6a0" stroke="#b8a070" strokeWidth={0.4} />
              <rect x={x - 0.6} y={y - 1.4} width={9.2} height={1.6} fill="#c8a24a" />
              <rect x={x + 3} y={y + 7} width={2} height={1} fill="#5a3f2a" />
            </g>
          ))}
          <g fill="#3b3430">{[[30, 50], [46, 47], [62, 52], [80, 49], [52, 44]].map(([x, y], i) => <circle key={i} cx={x} cy={y} r={0.5}><animate attributeName="cy" values={`${y};${y - 2};${y}`} dur={`${1.4 + i * 0.3}s`} repeatCount="indefinite" /></circle>)}</g>
          <rect x={112} y={44} width={22} height={16} fill="#e6d4b0" />
          <path d="M108 45 L123 34 L138 45 Z" fill="#b08a4a" />
          <Window x={118} y={49} lit={lit} />
        </g>
      );
    case "cave": {
      const ebb = mark(s, "ebb");
      return (
        <g>
          <path d="M0 24 C30 14 70 20 90 12 C120 4 150 14 160 10 L160 90 L0 90 Z" fill="#7d7468" />
          <path d="M44 74 C44 46 60 34 80 34 C100 34 116 46 116 74 Z" fill="#1f1d1b" />
          {ebb && <ellipse cx={80} cy={58} rx={8} ry={5} fill="#bfe8f0" opacity={0.6}><animate attributeName="opacity" values="0.35;0.75;0.35" dur="3s" repeatCount="indefinite" /></ellipse>}
          <path d={`M0 ${ebb ? 82 : 72} C40 ${ebb ? 80 : 70} 120 ${ebb ? 84 : 74} 160 ${ebb ? 81 : 71} L160 90 L0 90 Z`} fill="#4f86a2" opacity={0.9} />
          <Waves y={ebb ? 85 : 76} />
          {[[20, 70], [136, 66], [30, 60]].map(([x, y], i) => <ellipse key={i} cx={x} cy={y} rx={5} ry={2.4} fill="#6b6358" />)}
        </g>
      );
    }
    case "isle":
      return (
        <g>
          <rect y={52} width={160} height={38} fill="#5f8fae" />
          <path d="M18 60 C34 40 70 34 96 38 C120 42 140 50 146 60 C120 64 60 66 18 60 Z" fill="#8fae6a" />
          <path d="M40 58 C52 48 70 44 86 46" stroke="#6f8e4e" strokeWidth={0.8} fill="none" />
          <g transform="translate(128 34)">
            <rect x={-1.4} y={0} width={2.8} height={14} fill="#f2efe6" />
            <rect x={-1.4} y={4} width={2.8} height={2} fill="#c0453a" />
            <rect x={-1.8} y={-2} width={3.6} height={2.4} fill={(s.glow ?? 0) > 0.5 ? "#ffe9a8" : "#5d6b78"} />
            {(s.glow ?? 0) > 0.5 && <path d="M0 -1 L-70 -10 L-70 8 Z" fill="url(#beam)" opacity={0.5} style={{ visibility: "visible" }} />}
          </g>
          {[[60, 50], [68, 52], [76, 49]].map(([x, y], i) => (
            <g key={i}><rect x={x} y={y} width={5} height={4} fill="#e6d9bf" /><path d={`M${x - 1} ${y} L${x + 2.5} ${y - 3} L${x + 6} ${y} Z`} fill="#8a5a3a" /></g>
          ))}
          <Waves y={72} />
          {[[30, 76], [110, 80]].map(([x, y], i) => (
            <g key={i} transform={`translate(${x} ${y})`}><path d="M-5 0 L5 0 L3 2 L-3 2 Z" fill="#8a5a3a" /><path d="M0.4 -6 L4 -1 L0.4 -1 Z" fill="#f2ead8" /><rect x={-0.2} y={-6} width={0.4} height={6} fill="#4a3424" /></g>
          ))}
        </g>
      );
    default: // the whole vale, for openings
      return (
        <g>
          <path d="M0 60 C30 44 60 50 90 44 C120 38 140 46 160 42 L160 90 L0 90 Z" fill="#93a675" />
          <path d="M0 74 C40 68 70 74 100 70 C130 66 150 70 160 68" stroke={waterColor(s.water ?? 0)} strokeWidth={2.6} fill="none" />
          {[[60, 54], [70, 56], [78, 53]].map(([x, y], i) => (
            <g key={i}><rect x={x} y={y} width={6} height={5} fill="#ddc9a6" /><path d={`M${x - 1} ${y} L${x + 3} ${y - 4} L${x + 7} ${y} Z`} fill="#a58a46" /></g>
          ))}
          <g transform="translate(120 34)"><rect x={0} y={0} width={10} height={7} fill={stone} /><rect x={-2} y={-3} width={3} height={10} fill={stone} /><rect x={9} y={-3} width={3} height={10} fill={stone} /></g>
          <g transform="translate(30 42)">{[0, 3, 6, 9, 12].map((x) => <rect key={x} x={x} y={x === 6 && !mark(s, "stone_raised") ? 3 : 0} width={1.6} height={x === 6 && !mark(s, "stone_raised") ? 1.4 : 4} fill="#7d7a72" />)}</g>
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
  const lit = hour >= 4 || (s.glow ?? 0) > 0.6;
  const [sx, sy] = SUN[hour];
  const kind = place?.kind ?? "vale";
  const shown = people.slice(0, 7);
  const ground = night ? "#26303a" : hour === 4 ? "#8f8a5a" : "#a3a364";
  return (
    <svg viewBox="0 0 160 90" className={className} role="img" aria-label={label} preserveAspectRatio="xMidYMid slice">
      <defs>
        <linearGradient id={`sky${id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={top} /><stop offset="1" stopColor={bottom} /></linearGradient>
        <linearGradient id="beam" x1="1" y1="0" x2="0" y2="0"><stop offset="0" stopColor="#fff2b0" stopOpacity={0.9} /><stop offset="1" stopColor="#fff2b0" stopOpacity={0} /></linearGradient>
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

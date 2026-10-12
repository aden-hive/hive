import type { ValeFeedItem, ValePlace, ValeTruth, ValeVillager } from "@/api/vale";
import { PortraitArt, type PersonArt } from "./Portrait";
import type { ValeStrings } from "./strings";

/** The Hollowbrook's course on the map, and which place's water colours each stretch. */
const RIVER: [string, [number, number]][] = [
  ["mine", [16, 25]], ["", [20, 36]], ["mill", [25, 44]], ["", [36, 52]],
  ["ashmere", [44, 58]], ["", [38, 70]], ["fenford", [32, 80]],
];
const FLOOD: [number, number][] = [[36, 52], [50, 66], [60, 74]];

function mix(a: string, b: string, t: number): string {
  const pa = a.match(/\w\w/g)!.map((h) => parseInt(h, 16));
  const pb = b.match(/\w\w/g)!.map((h) => parseInt(h, 16));
  return "#" + pa.map((x, i) => Math.round(x + (pb[i] - x) * t).toString(16).padStart(2, "0")).join("");
}

const water = (blight: number) => mix("4a7d97", "a8352c", Math.min(1, blight / 0.7));

function Glyph({ p }: { p: ValePlace }) {
  const x = p.x, y = p.y * 0.92;
  const tri = (dx: number) => `M${x + dx - 2} ${y + 1.4} L${x + dx} ${y - 1.8} L${x + dx + 2} ${y + 1.4}`;
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 0.35, strokeLinejoin: "round" as const };
  switch (p.id) {
    case "mine":
      return <g><path d={tri(-1.8)} {...common} /><path d={tri(1.2)} {...common} /></g>;
    case "thornkeep":
      return <path d={`M${x - 2.4} ${y + 1.6} V${y - 1} h1 v-0.8 h0.9 v0.8 h1 v-0.8 h0.9 v0.8 h1 V${y + 1.6} Z`} {...common} />;
    case "mill":
      return <g><circle cx={x} cy={y} r={1.7} {...common} /><path d={`M${x - 1.7} ${y} H${x + 1.7} M${x} ${y - 1.7} V${y + 1.7}`} {...common} /></g>;
    case "ashmere":
      return <g>{[-2.2, 0, 2.2].map((dx) => <path key={dx} d={`M${x + dx - 0.9} ${y + 1.2} V${y} L${x + dx} ${y - 1} L${x + dx + 0.9} ${y} V${y + 1.2} Z`} {...common} />)}</g>;
    case "chapel":
      return <path d={`M${x - 1.2} ${y + 1.6} V${y - 0.2} L${x} ${y - 1.4} L${x + 1.2} ${y - 0.2} V${y + 1.6} Z M${x} ${y - 1.4} V${y - 3} M${x - 0.6} ${y - 2.4} H${x + 0.6}`} {...common} />;
    case "barrow_hill":
      return <path d={`M${x - 3.4} ${y + 1.6} Q${x} ${y - 2.6} ${x + 3.4} ${y + 1.6}`} {...common} />;
    case "fold":
      return <path d={`M${x - 2.4} ${y + 1.2} h4.8 M${x - 2.4} ${y + 1.2} v-1.6 M${x} ${y + 1.2} v-1.6 M${x + 2.4} ${y + 1.2} v-1.6 M${x - 2.4} ${y - 0.2} h4.8`} {...common} />;
    case "mirewood":
      return <g>{[[-2.2, 0.4], [0, -0.6], [2.2, 0.5]].map(([dx, dy]) => <path key={dx} d={`M${x + dx} ${y + dy - 1.3} L${x + dx - 0.9} ${y + dy + 0.6} H${x + dx + 0.9} Z`} {...common} />)}</g>;
    case "fenford":
      return <path d={`M${x - 2.5} ${y + 1} h5 M${x - 1.8} ${y + 1} v-1.6 h3.6 v1.6 M${x - 2.6} ${y - 0.6} L${x} ${y - 1.9} L${x + 2.6} ${y - 0.6}`} {...common} />;
    default:
      return <circle cx={x} cy={y} r={1.5} {...common} />;
  }
}

/** The seven stones on Barrow Hill: the fourth lies down until it is raised. */
function Stones({ p, raised, hum, awake }: { p: ValePlace; raised: boolean; hum: boolean; awake: boolean }) {
  const x = p.x, y = p.y * 0.92;
  return (
    <g>
      {Array.from({ length: 7 }, (_, i) => {
        const a = Math.PI * (0.15 + (0.7 * i) / 6);
        const sx = x - Math.cos(a) * 3.2, sy = y + 0.6 - Math.sin(a) * 1.6;
        const down = i === 3 && !raised;
        return <rect key={i} x={sx - 0.18} y={sy - (down ? 0.2 : 0.9)} width={0.36} height={down ? 0.36 : 0.9}
          fill={awake ? "#1d7a74" : hum ? "#6d9f9b" : "currentColor"} />;
      })}
      {awake && <circle cx={x} cy={y - 0.2} r={4.6} fill="none" stroke="#1d7a74" strokeWidth={0.3} strokeDasharray="0.8 0.6" />}
    </g>
  );
}

export interface ValeMapProps {
  places: ValePlace[];
  villagers: ValeVillager[];
  truth: ValeTruth;
  stirred: Set<string>;
  marks: ValeFeedItem[];
  onPick: (vid: string) => void;
  title: string;
  ui: ValeStrings;
  art: Record<string, PersonArt>;
}

export default function ValeMap({ places, villagers, truth, stirred, marks, onPick, title, ui, art }: ValeMapProps) {
  const byId = Object.fromEntries(places.map((p) => [p.id, p]));
  const xy = (id: string | null | undefined): [number, number] => {
    const p = id ? byId[id] : undefined;
    return p ? [p.x, p.y * 0.92] : [50, 46];
  };
  const groups: Record<string, ValeVillager[]> = {};
  for (const v of villagers) {
    const key = v.loc ?? `road:${v.travel?.to ?? ""}`;
    (groups[key] = groups[key] || []).push(v);
  }
  let lastPlace = "mine";
  return (
    <svg viewBox="0 0 100 92" className="w-full h-auto rounded-lg border border-border/60 bg-muted/20 text-foreground/80" role="img"
      aria-label={ui.mapLabel(title)}>
      {places.flatMap((p) => p.roads.filter((r) => p.id < r).map((r) => {
        const [x1, y1] = xy(p.id), [x2, y2] = xy(r);
        return <line key={`${p.id}-${r}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="currentColor" strokeOpacity={0.35} strokeWidth={0.25} strokeDasharray="0.8 0.9" />;
      }))}
      {RIVER.slice(0, -1).map(([name, [x1, y1]], i) => {
        const owner = RIVER[i + 1][0] || lastPlace;
        if (name) lastPlace = name;
        const [x2, y2] = RIVER[i + 1][1];
        return <path key={i} d={`M${x1} ${y1} Q${(x1 + x2) / 2 + 2} ${(y1 + y2) / 2} ${x2} ${y2}`} stroke={water(truth.blight[owner] ?? 0)}
          strokeWidth={1.1} fill="none" strokeLinecap="round" opacity={0.85} />;
      })}
      <path d={`M${FLOOD[0][0]} ${FLOOD[0][1]} Q${FLOOD[1][0]} ${FLOOD[1][1]} ${FLOOD[2][0]} ${FLOOD[2][1]}`} stroke={water(truth.blight.mirewood ?? 0)}
        strokeWidth={0.6} fill="none" strokeDasharray="1.2 0.8" opacity={0.7} />
      {places.map((p) => {
        const [x, y] = xy(p.id);
        return (
          <g key={p.id}>
            {p.id === "barrow_hill"
              ? <g><Glyph p={p} /><Stones p={p} raised={!!truth.stone_raised} hum={truth.stone_hum > 0} awake={truth.ullr_awake > 0} /></g>
              : <Glyph p={p} />}
            {p.id === "mine" && <circle cx={x} cy={y + 0.4} r={0.7} fill={truth.shaft_open ? "#a8352c" : "#5a7254"}>
              <title>{truth.shaft_open ? ui.doorOpenTitle : ui.doorShutTitle}</title></circle>}
            <text x={x} y={y + 5} textAnchor="middle" fontSize={2.8} fill="currentColor" style={{ fontFamily: "serif" }}>{p.name}</text>
          </g>
        );
      })}
      {marks.map((m, i) => {
        const [x, y] = xy((m.place as string) || null);
        const color = m.by === "overgod" ? "#c8a24a" : "#a8352c";
        return <path key={i} d={`M${x + 3.6 + (i % 3) * 1.4} ${y - 4.2} l0.9 0.9 l-0.9 0.9 l-0.9 -0.9 z`} fill={color}>
          <title>{String(m.text ?? "")}</title></path>;
      })}
      {Object.entries(groups).map(([key, vs]) =>
        vs.map((v, i) => {
          let cx: number, cy: number;
          if (v.loc) {
            const [x, y] = xy(v.loc);
            cx = x + 5.2 + (i % 4) * 3.6 - 5.4;
            cy = y - 7.6 + Math.floor(i / 4) * 3.6;
          } else {
            const [x1, y1] = xy(v.travel?.from), [x2, y2] = xy(v.travel?.to);
            cx = (x1 + x2) / 2 + i * 1.2;
            cy = (y1 + y2) / 2;
          }
          return (
            <g key={`${key}-${v.id}`} transform={`translate(${cx.toFixed(2)} ${cy.toFixed(2)})`} className="cursor-pointer" onClick={() => onPick(v.id)}>
              {stirred.has(v.id) && (
                <circle r={1.6} fill="none" stroke="#c8a24a" strokeWidth={0.4}>
                  <animate attributeName="r" values="1.6;3.4" dur="1.4s" repeatCount="indefinite" />
                  <animate attributeName="opacity" values="1;0" dur="1.4s" repeatCount="indefinite" />
                </circle>
              )}
              <svg x={-1.7} y={-1.7} width={3.4} height={3.4} viewBox="0 0 64 64" style={{ overflow: "visible" }}>
                <defs><clipPath id={`mt-${v.id}`}><circle cx={32} cy={32} r={31} /></clipPath></defs>
                <g clipPath={`url(#mt-${v.id})`}>
                  {art[v.id] ? <PortraitArt art={art[v.id]} health={v.health} bg={v.color + "55"} /> : <rect width={64} height={64} fill={v.color} />}
                </g>
                <circle cx={32} cy={32} r={31} fill="none" stroke={v.health >= 2 ? "#a8352c" : v.health === 1 ? "#c98b2b" : v.color} strokeWidth={v.health ? 7 : 5} />
              </svg>
              <title>{`${v.name}${ui.listSep}${v.role}${v.health ? ` (${ui.health[v.health]})` : ""}`}</title>
            </g>
          );
        }),
      )}
    </svg>
  );
}

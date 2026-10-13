import type { ValeArt, ValeFeedItem, ValePlace, ValeScene, ValeVillager } from "@/api/vale";
import { PortraitArt, type PersonArt } from "./Portrait";
import type { ValeStrings } from "./strings";

function mix(a: string, b: string, t: number): string {
  const pa = a.match(/\w\w/g)!.map((h) => parseInt(h, 16));
  const pb = b.match(/\w\w/g)!.map((h) => parseInt(h, 16));
  return "#" + pa.map((x, i) => Math.round(x + (pb[i] - x) * t).toString(16).padStart(2, "0")).join("");
}

const waterColor = (troubled: number) => mix("4a7d97", "a8352c", Math.min(1, troubled / 0.7));

/** A place's mark on the map, by its kind (art.toml [places.<id>] kind). */
function Glyph({ p, kind, scene }: { p: ValePlace; kind: string; scene: ValeScene }) {
  const x = p.x, y = p.y * 0.92;
  const tri = (dx: number) => `M${x + dx - 2} ${y + 1.4} L${x + dx} ${y - 1.8} L${x + dx + 2} ${y + 1.4}`;
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 0.35, strokeLinejoin: "round" as const };
  const glow = scene.glow?.[p.id] ?? 0;
  switch (kind) {
    case "mine":
      return <g><path d={tri(-1.8)} {...common} /><path d={tri(1.2)} {...common} /></g>;
    case "keep":
      return <path d={`M${x - 2.4} ${y + 1.6} V${y - 1} h1 v-0.8 h0.9 v0.8 h1 v-0.8 h0.9 v0.8 h1 V${y + 1.6} Z`} {...common} />;
    case "mill":
      return <g><circle cx={x} cy={y} r={1.7} {...common} /><path d={`M${x - 1.7} ${y} H${x + 1.7} M${x} ${y - 1.7} V${y + 1.7}`} {...common} /></g>;
    case "village":
      return <g>{[-2.2, 0, 2.2].map((dx) => <path key={dx} d={`M${x + dx - 0.9} ${y + 1.2} V${y} L${x + dx} ${y - 1} L${x + dx + 0.9} ${y} V${y + 1.2} Z`} {...common} />)}</g>;
    case "chapel":
      return <path d={`M${x - 1.2} ${y + 1.6} V${y - 0.2} L${x} ${y - 1.4} L${x + 1.2} ${y - 0.2} V${y + 1.6} Z M${x} ${y - 1.4} V${y - 3} M${x - 0.6} ${y - 2.4} H${x + 0.6}`} {...common} />;
    case "stones":
      return <path d={`M${x - 3.4} ${y + 1.6} Q${x} ${y - 2.6} ${x + 3.4} ${y + 1.6}`} {...common} />;
    case "pasture":
      return <path d={`M${x - 2.4} ${y + 1.2} h4.8 M${x - 2.4} ${y + 1.2} v-1.6 M${x} ${y + 1.2} v-1.6 M${x + 2.4} ${y + 1.2} v-1.6 M${x - 2.4} ${y - 0.2} h4.8`} {...common} />;
    case "forest":
      return <g>{[[-2.2, 0.4], [0, -0.6], [2.2, 0.5]].map(([dx, dy]) => <path key={dx} d={`M${x + dx} ${y + dy - 1.3} L${x + dx - 0.9} ${y + dy + 0.6} H${x + dx + 0.9} Z`} {...common} />)}</g>;
    case "ford":
      return <path d={`M${x - 2.5} ${y + 1} h5 M${x - 1.8} ${y + 1} v-1.6 h3.6 v1.6 M${x - 2.6} ${y - 0.6} L${x} ${y - 1.9} L${x + 2.6} ${y - 0.6}`} {...common} />;
    case "lighthouse":
      return (
        <g>
          {glow > 0.5 && <circle cx={x} cy={y - 2.4} r={4.5} fill="#ffe28a" opacity={0.35}><animate attributeName="opacity" values="0.2;0.5;0.2" dur="3s" repeatCount="indefinite" /></circle>}
          <path d={`M${x - 1} ${y + 1.6} L${x - 0.6} ${y - 1.8} H${x + 0.6} L${x + 1} ${y + 1.6} Z M${x - 0.9} ${y - 1.8} h1.8 v-1 h-1.8 Z`} {...common} />
          <circle cx={x} cy={y - 2.3} r={0.45} fill={glow > 0.5 ? "#f2b632" : "currentColor"} />
        </g>
      );
    case "harbor":
      return <path d={`M${x - 2.6} ${y + 0.6} h5.2 l-1 1.2 h-3.2 Z M${x} ${y + 0.6} V${y - 2.2} L${x + 1.8} ${y + 0.2}`} {...common} />;
    case "orchard":
      return <g>{[-1.8, 1.8].map((dx) => <g key={dx}><circle cx={x + dx} cy={y - 0.6} r={1.2} {...common} /><path d={`M${x + dx} ${y + 0.6} V${y + 1.6}`} {...common} /></g>)}</g>;
    case "garden":
      return <g><rect x={x - 2.2} y={y - 0.6} width={1.8} height={2} {...common} /><rect x={x + 0.4} y={y - 0.6} width={1.8} height={2} {...common} /><path d={`M${x - 2.4} ${y - 0.6} h2.2 M${x + 0.2} ${y - 0.6} h2.2`} {...common} /></g>;
    case "cave":
      return <path d={`M${x - 2.6} ${y + 1.4} Q${x - 2.6} ${y - 2} ${x} ${y - 2} Q${x + 2.6} ${y - 2} ${x + 2.6} ${y + 1.4} M${x - 1.2} ${y + 1.4} Q${x - 1.2} ${y - 0.4} ${x} ${y - 0.4} Q${x + 1.2} ${y - 0.4} ${x + 1.2} ${y + 1.4}`} {...common} />;
    default:
      return <circle cx={x} cy={y} r={1.5} {...common} />;
  }
}

/** A place of standing stones: the fourth lies down until the world marks it raised. */
function Stones({ p, scene }: { p: ValePlace; scene: ValeScene }) {
  const x = p.x, y = p.y * 0.92;
  const raised = Boolean(scene.marks?.stone_raised), awake = Boolean(scene.marks?.awake), hum = Boolean(scene.marks?.hum);
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
  scene: ValeScene;
  art: ValeArt;
  stirred: Set<string>;
  marks: ValeFeedItem[];
  onPick: (vid: string) => void;
  title: string;
  ui: ValeStrings;
}

export default function ValeMap({ places, villagers, scene, art, stirred, marks, onPick, title, ui }: ValeMapProps) {
  const byId = Object.fromEntries(places.map((p) => [p.id, p]));
  const kinds: Record<string, string> = Object.fromEntries(places.map((p) => [p.id, art.places?.[p.id]?.kind ?? ""]));
  const people: Record<string, PersonArt> = art.people ?? {};
  const map = art.map ?? {};
  const xy = (id: string | null | undefined): [number, number] => {
    const p = id ? byId[id] : undefined;
    return p ? [p.x, p.y * 0.92] : [50, 46];
  };
  const groups: Record<string, ValeVillager[]> = {};
  for (const v of villagers) {
    const key = v.loc ?? `road:${v.travel?.to ?? ""}`;
    (groups[key] = groups[key] || []).push(v);
  }
  const water = (owner: string) => waterColor(Number(scene.water?.[owner] ?? 0));
  return (
    <svg viewBox="0 0 100 92" className="w-full h-auto rounded-lg border border-border/60 bg-muted/20 text-foreground/80" role="img"
      aria-label={ui.mapLabel(title)}>
      {map.coast && (
        <g>
          <rect width={100} height={92} fill="#4a7d97" opacity={0.22} />
          <path d={`M${map.coast.map(([x, y]) => `${x} ${y * 0.92}`).join(" L")} Z`} fill="#9db87a" opacity={0.35} stroke="#4a7d97" strokeOpacity={0.5} strokeWidth={0.4} strokeLinejoin="round" />
        </g>
      )}
      {places.flatMap((p) => p.roads.filter((r) => p.id < r).map((r) => {
        const [x1, y1] = xy(p.id), [x2, y2] = xy(r);
        return <line key={`${p.id}-${r}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="currentColor" strokeOpacity={0.35} strokeWidth={0.25} strokeDasharray="0.8 0.9" />;
      }))}
      {(map.streams ?? []).map((stream, si) => {
        let last = stream.points[0]?.[0] ?? "";
        return stream.points.slice(0, -1).map(([name, x1, y1], i) => {
          const [nextName, x2, y2] = stream.points[i + 1];
          const owner = nextName || last;
          if (name) last = name;
          return <path key={`${si}-${i}`} d={`M${x1} ${y1} Q${(x1 + x2) / 2 + 2} ${(y1 + y2) / 2} ${x2} ${y2}`} stroke={water(owner)}
            strokeWidth={1.1} fill="none" strokeLinecap="round" opacity={0.85} />;
        });
      })}
      {(map.floods ?? []).map((f, i) => f.points.length >= 3 && (
        <path key={`f${i}`} d={`M${f.points[0][0]} ${f.points[0][1]} Q${f.points[1][0]} ${f.points[1][1]} ${f.points[2][0]} ${f.points[2][1]}`} stroke={water(f.owner)}
          strokeWidth={0.6} fill="none" strokeDasharray="1.2 0.8" opacity={0.7} />
      ))}
      {places.map((p) => {
        const [x, y] = xy(p.id);
        return (
          <g key={p.id}>
            <Glyph p={p} kind={kinds[p.id]} scene={scene} />
            {kinds[p.id] === "stones" && <Stones p={p} scene={scene} />}
            {kinds[p.id] === "mine" && "deep_door" in (scene.marks ?? {}) && (
              <circle cx={x} cy={y + 0.4} r={0.7} fill={scene.marks.deep_door ? "#a8352c" : "#5a7254"} />
            )}
            <text x={x} y={y + 5} textAnchor="middle" fontSize={2.8} fill="currentColor" style={{ fontFamily: "serif" }}>{p.name.charAt(0).toUpperCase() + p.name.slice(1)}</text>
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
                  {people[v.id] ? <PortraitArt art={people[v.id]} health={v.health} bg={v.color + "55"} /> : <rect width={64} height={64} fill={v.color} />}
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

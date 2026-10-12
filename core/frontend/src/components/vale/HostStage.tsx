import { useEffect, useMemo, useRef, useState } from "react";
import { Crown, Dices, Eye, Loader2, Pause, Play, SkipForward } from "lucide-react";
import { artBase, type ValeBeat, type ValeFeedItem, type ValeGame, type ValeHostPart } from "@/api/vale";
import Portrait from "./Portrait";
import SceneArt, { type SceneFigure, type SceneState } from "./SceneArt";
import { capital, type ValeStrings } from "./strings";

const BAND_COLOR: Record<string, string> = {
  critical: "#5a7254", success: "#8fa889", partial: "#c8a24a", failure: "#9aa4a0", fumble: "#a8352c",
};
export const SPEEDS: Record<string, number> = { slow: 0.65, normal: 1, fast: 2 };

// ---------------------------------------------------------------------------- timing

interface Segment { name: "type" | "hold" | "before" | "beforeHold" | "roll" | "land" | "after" | "afterHold"; ms: number }

function reading(text: string, ui: ValeStrings): [number, number] {
  const type = (text.length * 1000) / ui.typeCps;
  const read = (text.length * 1000) / ui.readCps;
  return [type, Math.max(900, read - type)];
}

/** How long each part of a beat takes at normal speed: words type in, stay long enough to read; a die spins, lands, tells. */
function timeline(beat: ValeBeat, ui: ValeStrings): Segment[] {
  if (beat.kind === "roll") {
    const [bt, bh] = reading(beat.before ?? "", ui);
    const [at, ah] = reading(beat.after ?? "", ui);
    return [
      { name: "before", ms: bt }, { name: "beforeHold", ms: Math.max(700, bh * 0.6) },
      { name: "roll", ms: 1500 }, { name: "land", ms: 1100 },
      { name: "after", ms: at }, { name: "afterHold", ms: ah },
    ];
  }
  const [t, h] = reading(beat.text ?? "", ui);
  return [{ name: "type", ms: t }, { name: "hold", ms: h + (beat.kind === "open" ? 600 : beat.kind === "turn" ? 1800 : 0) }];
}

function at(segments: Segment[], elapsed: number): { name: Segment["name"]; into: number; done: boolean } {
  let t = elapsed;
  for (const s of segments) {
    if (t < s.ms) return { name: s.name, into: t, done: false };
    t -= s.ms;
  }
  const last = segments[segments.length - 1];
  return { name: last.name, into: last.ms, done: true };
}

/** Milliseconds of play since `key` began, scaled by speed; stands still while paused. */
function useElapsed(key: string, running: boolean, speed: number): [number, (ms: number) => void] {
  const [elapsed, setElapsed] = useState(0);
  const last = useRef<number | null>(null);
  useEffect(() => { setElapsed(0); last.current = null; }, [key]);
  useEffect(() => {
    if (!running) { last.current = null; return; }
    let raf = 0;
    const tick = (now: number) => {
      if (last.current !== null) setElapsed((e) => e + (now - last.current!) * speed);
      last.current = now;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [running, speed, key]);
  return [elapsed, setElapsed];
}

const typed = (text: string, ms: number, ui: ValeStrings) => text.slice(0, Math.ceil((ms * ui.typeCps) / 1000));

// ---------------------------------------------------------------------------- the stage

export interface StageProps {
  game: ValeGame;
  parts: ValeHostPart[];
  /** Parts before this index were played before the page opened: shown, not replayed. */
  startAt: number;
  ui: ValeStrings;
  speed: string;
  paused: boolean;
  running: boolean;
  phase: string;
  live: ValeFeedItem[];
  onSpeed: (s: string) => void;
  onPause: (p: boolean) => void;
  onPlaying: (part: ValeHostPart | null) => void;
  onPower: (power: string) => void;
}

export default function HostStage({ game, parts, startAt, ui, speed, paused, running, phase, live, onSpeed, onPause, onPlaying, onPower }: StageProps) {
  const [cursor, setCursor] = useState({ part: startAt, beat: 0 });
  const active = cursor.part < parts.length ? parts[cursor.part] : null;
  const beat = active?.beats[cursor.beat] ?? null;
  const segments = useMemo(() => (beat ? timeline(beat, ui) : []), [beat, ui]);
  const key = `${cursor.part}:${cursor.beat}`;
  const [elapsed, setElapsed] = useElapsed(key, !!beat && !paused, SPEEDS[speed] ?? 1);
  const pos = beat ? at(segments, elapsed) : null;

  useEffect(() => { onPlaying(active); }, [active, onPlaying]);
  useEffect(() => {
    if (!pos?.done || !active) return;
    setCursor((c) => (c.beat + 1 < active.beats.length ? { part: c.part, beat: c.beat + 1 } : { part: c.part + 1, beat: 0 }));
  }, [pos?.done, active]);

  const skip = () => { if (beat) setElapsed(segments.reduce((n, s) => n + s.ms, 0)); };
  const catchUp = () => setCursor({ part: parts.length, beat: 0 });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)) return;
      if (e.key === " ") { e.preventDefault(); onPause(!paused); }
      if (e.key === "ArrowRight") skip();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // What the stage shows: the beat playing now, else the last one played.
  const lastPart = parts[parts.length - 1];
  const shownPart = active ?? lastPart ?? null;
  const shownIndex = active ? cursor.beat : (lastPart?.beats.length ?? 1) - 1;
  const shownBeat = shownPart?.beats[shownIndex] ?? null;
  const backdrop = useMemo(() => {
    if (!shownPart) return null;
    for (let i = shownIndex; i >= 0; i--) {
      const b = shownPart.beats[i];
      if (b.kind === "scene" || b.kind === "open") return b;
      if (b.kind === "roll" && b.roll?.place) return { kind: "scene", place: b.roll.place, who: [b.roll.roller] } as ValeBeat;
    }
    return shownPart.beats[0];
  }, [shownPart, shownIndex]);
  const turn = shownPart?.beats.find((b) => b.kind === "turn");
  const showTurn = !!turn && (!active || shownBeat?.kind === "turn");
  const left = active ? active.beats.length - cursor.beat - 1 + parts.slice(cursor.part + 1).reduce((n, p) => n + p.beats.length, 0) : 0;
  const waiting = !active && running;

  const villager = (id: string) => game.villagers.find((v) => v.id === id);
  const figures = (ids: string[] | string | undefined): SceneFigure[] =>
    (Array.isArray(ids) ? ids : ids ? [ids] : []).map(villager).filter((v): v is NonNullable<typeof v> => !!v)
      .map((v) => ({ id: v.id, name: v.short, color: v.color, art: game.art?.people?.[v.id], health: v.health }));
  const t = game.truth;
  const place = backdrop?.kind === "scene" ? backdrop.place ?? null : null;
  const scene: SceneState = {
    hour: shownPart?.wave ?? game.last.wave,
    weather: t.weather_kind,
    winter: t.winter,
    blight: place ? t.blight[place] ?? 0 : Math.max(0, ...Object.values(t.blight)),
    shaftOpen: !!t.shaft_open,
    stoneRaised: !!t.stone_raised,
    ullrAwake: t.ullr_awake > 0,
    hum: t.stone_hum > 0,
  };
  const placeName = place ? game.places.find((p) => p.id === place)?.name : game.story.title;
  const when = shownPart ? capital(ui.dayWave(shownPart.day, game.waves[shownPart.wave] ?? "")) : "";

  return (
    <div className="space-y-2">
      <div data-vale="stage" className="relative rounded-lg overflow-hidden border border-border/60 bg-muted/30 aspect-[16/9]">
        <SceneArt className="absolute inset-0 w-full h-full" place={place ? game.art?.places?.[place] : { kind: "vale" }}
          s={scene} people={backdrop?.kind === "scene" ? figures(backdrop.who) : []} label={placeName} imageBase={artBase(game.story.id)} />
        <div className="absolute top-2 left-2 flex items-center gap-1.5">
          {when && <span className="rounded-full bg-black/55 text-white text-[11px] px-2 py-0.5">{when}</span>}
          {placeName && <span className="rounded-full bg-black/40 text-white/90 text-[11px] px-2 py-0.5">{placeName}</span>}
        </div>
        {shownPart?.title && <div className="absolute top-2 right-2 rounded-full bg-black/40 text-white/90 text-[11px] px-2 py-0.5 max-w-[45%] truncate">{shownPart.title}</div>}

        {shownBeat?.kind === "roll" && shownBeat.roll && (
          <RollCard beat={shownBeat} pos={active ? pos : null} game={game} ui={ui} />
        )}
        {shownBeat && shownBeat.kind !== "turn" && (
          <Caption beat={shownBeat} pos={active ? pos : null} ui={ui} game={game} />
        )}
        {waiting && (
          <div data-vale="waiting" className="absolute inset-0 bg-black/45 backdrop-blur-[1px] flex flex-col items-center justify-center gap-2 text-white px-4">
            <div className="flex items-center gap-2 text-sm"><Loader2 className="w-4 h-4 animate-spin" />{ui.phases[phase] ?? ui.moving}</div>
            <LiveStrip live={live} game={game} />
          </div>
        )}
      </div>

      <div className="flex items-center gap-1.5 text-[11px]">
        <button className="rounded-md border border-border/60 px-2 py-0.5 flex items-center gap-1 hover:bg-muted/40" onClick={() => onPause(!paused)}>
          {paused ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}{paused ? ui.play : ui.pause}
        </button>
        <button className="rounded-md border border-border/60 px-2 py-0.5 flex items-center gap-1 hover:bg-muted/40 disabled:opacity-40" disabled={!beat} onClick={skip}>
          <SkipForward className="w-3 h-3" />{ui.skipBeat}
        </button>
        <div className="flex rounded-md border border-border/60 overflow-hidden">
          {Object.keys(SPEEDS).map((s) => (
            <button key={s} onClick={() => onSpeed(s)} className={`px-2 py-0.5 ${speed === s ? "bg-foreground text-background" : "hover:bg-muted/40"}`}>{ui.speeds[s]}</button>
          ))}
        </div>
        {left > 0 && <span className="text-muted-foreground">{ui.beatsLeft(left)}</span>}
        {cursor.part < parts.length - 1 && <button className="ml-auto text-muted-foreground hover:text-foreground underline" onClick={catchUp}>{ui.catchUp}</button>}
      </div>

      {showTurn && turn && <TurnPanel beat={turn} pos={shownBeat?.kind === "turn" && active ? pos : null} game={game} ui={ui} onPower={onPower} />}
      {!active && !running && !parts.length && <p className="text-xs text-muted-foreground italic">{ui.waitingIdle}</p>}

      <Transcript parts={parts} upTo={cursor} game={game} ui={ui} />
    </div>
  );
}

// ---------------------------------------------------------------------------- beats on the stage

type Pos = { name: Segment["name"]; into: number; done: boolean } | null;

function Caption({ beat, pos, ui, game }: { beat: ValeBeat; pos: Pos; ui: ValeStrings; game: ValeGame }) {
  let text = beat.text ?? "";
  if (beat.kind === "roll") {
    const after = pos === null || ["after", "afterHold"].includes(pos.name);
    text = after ? beat.after ?? "" : beat.before ?? "";
    if (pos && pos.name === "after") text = typed(text, pos.into, ui);
    if (pos && pos.name === "before") text = typed(text, pos.into, ui);
  } else if (pos && pos.name === "type") {
    text = typed(text, pos.into, ui);
  }
  const aside = beat.kind === "aside" && typeof beat.who === "string" ? game.villagers.find((v) => v.id === beat.who) : null;
  return (
    <div className="absolute left-0 right-0 bottom-0 p-2 sm:p-3">
      <div className={`rounded-md px-3 py-2 text-[13px] sm:text-[14px] leading-relaxed text-white shadow-lg ${aside ? "bg-indigo-950/80 italic" : beat.kind === "open" ? "bg-black/70" : "bg-black/65"}`}>
        {aside && (
          <div className="flex items-center gap-1.5 mb-1 not-italic">
            <Portrait art={game.art?.people?.[aside.id]} color={aside.color} name={aside.short} size={22} health={aside.health} />
            <span className="text-[11px] font-medium">{aside.short}</span>
            <span className="text-[10px] text-white/60 flex items-center gap-0.5"><Eye className="w-3 h-3" />{ui.overhear}</span>
          </div>
        )}
        <span data-vale="caption" className="min-h-[1.5em] inline-block">{text || " "}</span>
      </div>
    </div>
  );
}

function RollCard({ beat, pos, game, ui }: { beat: ValeBeat; pos: Pos; game: ValeGame; ui: ValeStrings }) {
  const roll = beat.roll!;
  const check = roll.check;
  const v = game.villagers.find((x) => x.id === roll.roller);
  const phase = pos?.name ?? "afterHold";
  const before = phase === "before" || phase === "beforeHold";
  const rolling = phase === "roll";
  const landed = !before && !rolling;
  const shown = rolling ? 1 + (Math.floor((pos?.into ?? 0) / 55) * 37 + 11) % 100 : landed ? check.roll : null;
  const color = BAND_COLOR[roll.outcome] ?? "#9aa4a0";
  const net = check.target - check.base;
  const crit = Math.max(1, Math.floor(check.target / 5));
  const cut = (lo: number, hi: number) => Math.max(0, Math.min(hi, check.fumble - 1) - lo + 1);
  const zones: [string, number][] = [
    ["critical", cut(1, crit)], ["success", cut(crit + 1, check.target)], ["partial", cut(check.target + 1, check.target + 20)],
    ["failure", cut(check.target + 21, 100)], ["fumble", 101 - check.fumble],
  ];
  return (
    <div className="absolute inset-x-0 top-[12%] flex justify-center px-3">
      <div className="rounded-lg bg-background/92 shadow-xl border border-border/60 px-3 py-2.5 w-full max-w-[340px]">
        <div className="flex items-center gap-2">
          {v && <Portrait art={game.art?.people?.[v.id]} color={v.color} name={v.short} size={40} health={v.health} />}
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-semibold text-foreground truncate">{roll.who}</div>
            <div className="text-[11px] text-muted-foreground truncate" title={check.mods.map((m) => `${m.mod >= 0 ? "+" : "−"}${Math.abs(m.mod)} ${m.why}`).join(" · ")}>
              {game.skills[check.skill] ?? check.skill} {check.base}{net ? ` ${net > 0 ? "+" : "−"}${Math.abs(net)}` : ""} · {ui.needs(check.target)}
            </div>
          </div>
          <div className={`w-14 h-14 rounded-lg flex items-center justify-center font-mono text-2xl font-bold border-2 transition-colors ${rolling ? "animate-pulse" : ""}`}
            style={{ borderColor: landed ? color : "var(--border, #ccc)", color: landed ? color : undefined }}>
            {shown ?? <Dices className="w-6 h-6 text-muted-foreground" />}
          </div>
        </div>
        <div className="relative mt-2 flex h-2 rounded-sm overflow-hidden">
          {zones.filter(([, w]) => w > 0).map(([band, w]) => <span key={band} style={{ width: `${w}%`, background: BAND_COLOR[band], opacity: landed && band !== roll.outcome ? 0.45 : 1 }} />)}
          {shown !== null && <i className="absolute -top-0.5 -bottom-0.5 w-[3px] -ml-[1.5px] bg-foreground ring-1 ring-background" style={{ left: `${shown - 0.5}%`, transition: rolling ? "none" : "left .3s" }} />}
        </div>
        <div className="mt-1 h-4 text-center text-[12px] font-semibold uppercase tracking-wide" style={{ color }}>
          {landed ? ui.bands[roll.outcome] ?? roll.outcome : rolling ? ui.rolling : roll.what}
        </div>
      </div>
    </div>
  );
}

function TurnPanel({ beat, pos, game, ui, onPower }: { beat: ValeBeat; pos: Pos; game: ValeGame; ui: ValeStrings; onPower: (p: string) => void }) {
  const text = pos && pos.name === "type" ? typed(beat.text ?? "", pos.into, ui) : beat.text ?? "";
  const powers = (beat.powers ?? []).map((id) => game.overgod.powers.find((p) => p.id === id)).filter((p): p is NonNullable<typeof p> => !!p && !p.locked);
  return (
    <div className="rounded-lg border-2 border-primary/50 bg-primary/5 px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-primary font-semibold"><Crown className="w-3.5 h-3.5" />{ui.yourMove}</div>
      <p className="mt-1 text-[13.5px] leading-relaxed text-foreground">{text}</p>
      {powers.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {powers.map((p) => (
            <button key={p.id} onClick={() => onPower(p.id)} disabled={!p.affordable}
              className="rounded-full border border-primary/60 bg-background px-2.5 py-0.5 text-[12px] text-foreground hover:bg-primary/10 disabled:opacity-40">
              {p.name} · {p.cost} {ui.awe}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function LiveStrip({ live, game }: { live: ValeFeedItem[]; game: ValeGame }) {
  const latest = new Map<string, string>();
  for (const i of live) {
    const text = ((i.texts as string[]) || []).join(" ") || String(i.summary ?? "");
    if (i.agent && text) latest.set(String(i.agent), text);
  }
  const rows = [...latest.entries()].slice(-5);
  return (
    <div className="w-full max-w-[420px] space-y-1">
      {rows.map(([id, text]) => {
        const v = game.villagers.find((x) => x.id === id);
        if (!v) return null;
        return (
          <div key={id} className="flex items-center gap-2 text-[12px] animate-in fade-in">
            <Portrait art={game.art?.people?.[id]} color={v.color} name={v.short} size={22} health={v.health} />
            <span className="font-medium shrink-0">{v.short}</span>
            <span className="truncate text-white/80">{text}</span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------- what was said, newest first

function Transcript({ parts, upTo, game, ui }: { parts: ValeHostPart[]; upTo: { part: number; beat: number }; game: ValeGame; ui: ValeStrings }) {
  const played = parts
    .map((p, i) => ({ p, beats: i < upTo.part ? p.beats : i === upTo.part ? p.beats.slice(0, upTo.beat) : [] }))
    .filter((x) => x.beats.length)
    .slice(-6)
    .reverse();
  if (!played.length) return null;
  return (
    <div className="max-h-[42vh] overflow-y-auto pr-1 space-y-3">
      {played.map(({ p, beats }) => (
        <section key={p.seq}>
          <h4 className="text-[11px] text-muted-foreground mb-1">{capital(ui.dayWave(p.day, game.waves[p.wave] ?? ""))}{p.title ? ` · ${p.title}` : ""}</h4>
          <ol className="space-y-1">
            {beats.map((b, i) => <TranscriptBeat key={i} beat={b} game={game} ui={ui} />)}
          </ol>
        </section>
      ))}
    </div>
  );
}

function TranscriptBeat({ beat, game, ui }: { beat: ValeBeat; game: ValeGame; ui: ValeStrings }) {
  const who = Array.isArray(beat.who) ? beat.who : beat.who ? [beat.who] : beat.roll ? [beat.roll.roller] : [];
  const faces = who.map((id) => game.villagers.find((v) => v.id === id)).filter((v): v is NonNullable<typeof v> => !!v).slice(0, 3);
  const text = beat.kind === "roll" ? beat.after : beat.text;
  return (
    <li className={`flex gap-2 text-[12.5px] leading-relaxed ${beat.kind === "aside" ? "italic text-foreground/70" : beat.kind === "turn" ? "text-primary" : "text-foreground/90"}`}>
      <span className="flex -space-x-1.5 shrink-0 w-[30px] pt-0.5">
        {faces.length ? faces.map((v) => <Portrait key={v.id} art={game.art?.people?.[v.id]} color={v.color} name={v.short} size={18} health={v.health} />)
          : beat.kind === "turn" ? <Crown className="w-3.5 h-3.5 text-primary" /> : null}
      </span>
      <span>
        {beat.kind === "roll" && beat.roll && (
          <b className="mr-1 font-mono text-[11px]" style={{ color: BAND_COLOR[beat.roll.outcome] }}>
            🎲{beat.roll.check.roll}/{beat.roll.check.target} {ui.bands[beat.roll.outcome] ?? beat.roll.outcome}
          </b>
        )}
        {text}
      </span>
    </li>
  );
}

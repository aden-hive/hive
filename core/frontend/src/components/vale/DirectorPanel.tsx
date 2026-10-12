import { useState } from "react";
import { Check, Circle, Crown, Loader2, Lock } from "lucide-react";
import type { ValeGame, ValePower } from "@/api/vale";
import { valeStrings } from "./strings";

function PowerForm({ power, game, busy, onCast }: {
  power: ValePower; game: ValeGame; busy: boolean; onCast: (args: Record<string, unknown>) => void;
}) {
  const ui = valeStrings(game.lang);
  const [args, setArgs] = useState<Record<string, string>>({});
  const set = (k: string, v: string) => setArgs((a) => ({ ...a, [k]: v }));
  const ready = power.params.every((p) => p.kind === "days" || (args[p.name] ?? "").trim());
  const field = "w-full bg-muted/30 border border-border/50 rounded-md px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40";
  return (
    <form className="mt-2 space-y-1.5" onSubmit={(e) => { e.preventDefault(); if (ready) onCast(args); }}>
      {power.params.map((p) => (
        <label key={p.name} className="block text-[11px] text-muted-foreground">
          {p.label}
          {p.kind === "person" && (
            <select className={field} value={args[p.name] ?? ""} onChange={(e) => set(p.name, e.target.value)}>
              <option value="">{ui.choose}</option>
              {game.villagers.filter((v) => !(power.id === "reveal" && game.overgod.revealed.includes(v.id))).map((v) => (
                <option key={v.id} value={v.id}>{v.name}{game.overgod.known_by.includes(v.id) ? ui.knowsVoice : ""}</option>
              ))}
            </select>
          )}
          {p.kind === "place" && (
            <select className={field} value={args[p.name] ?? ""} onChange={(e) => set(p.name, e.target.value)}>
              <option value="">{ui.choose}</option>
              {game.places.map((pl) => <option key={pl.id} value={pl.id}>{pl.name}</option>)}
            </select>
          )}
          {p.kind === "god" && (
            <select className={field} value={args[p.name] ?? ""} onChange={(e) => set(p.name, e.target.value)}>
              <option value="">{ui.choose}</option>
              {["god", "outer", "ullr"].map((id) => <option key={id} value={id}>{game.gods[id] ?? id}</option>)}
            </select>
          )}
          {p.kind === "days" && (
            <input type="number" min={1} max={7} className={field} value={args[p.name] ?? "3"} onChange={(e) => set(p.name, e.target.value)} />
          )}
          {p.kind === "text" && (
            <textarea rows={3} className={`${field} resize-y`} placeholder={ui.speak}
              value={args[p.name] ?? ""} onChange={(e) => set(p.name, e.target.value)} />
          )}
        </label>
      ))}
      <button type="submit" disabled={!ready || busy}
        className="w-full rounded-md bg-primary/90 hover:bg-primary text-primary-foreground text-xs font-medium py-1.5 disabled:opacity-40 flex items-center justify-center gap-1.5">
        {busy && <Loader2 className="w-3 h-3 animate-spin" />}
        {game.status === "running" ? ui.castLater : ui.cast} · {power.cost} {ui.awe}
      </button>
    </form>
  );
}

export default function DirectorPanel({ game, busy, error, onCast, open: openOutside, onOpen }: {
  game: ValeGame; busy: boolean; error: string | null; onCast: (power: string, args: Record<string, unknown>) => void;
  open?: string | null; onOpen?: (power: string | null) => void;
}) {
  const ui = valeStrings(game.lang);
  const [openInside, setOpenInside] = useState<string | null>(null);
  const open = openOutside !== undefined ? openOutside : openInside;
  const setOpen = onOpen ?? setOpenInside;
  const o = game.overgod;
  const tiers = [1, 2, 3, 4].map((t) => ({ tier: t, powers: o.powers.filter((p) => p.tier === t) }));
  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-baseline justify-between">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-1.5"><Crown className="w-4 h-4 text-primary" /> {ui.oneAbove}</h3>
          <span className="font-mono text-xs text-muted-foreground">{ui.tier}: {o.tier_name}</span>
        </div>
        <div className="mt-2 flex items-center gap-2">
          <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
            <div className="h-full bg-primary transition-all" style={{ width: `${(100 * o.awe) / o.cap}%` }} />
          </div>
          <span className="font-mono text-xs text-foreground">{o.awe.toFixed(1)} / {o.cap} {ui.awe}</span>
        </div>
        <p className="mt-1 text-[11px] text-muted-foreground">
          {ui.aweNote}
          {game.queue.length ? ui.queued(game.queue.length) : ""}
        </p>
      </div>

      <div>
        <h4 className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1.5">{ui.chapters}</h4>
        <ol className="space-y-1.5">
          {o.chapters.map((c) => (
            <li key={c.id} className={`flex gap-2 text-xs ${c.status === "later" ? "opacity-50" : ""}`}>
              {c.status === "done" ? <Check className="w-3.5 h-3.5 text-primary mt-0.5 shrink-0" /> : <Circle className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${c.status === "current" ? "text-primary" : ""}`} />}
              <span>
                <b className="text-foreground">{c.title}{ui.titleStop}</b> <span className="text-foreground/80">{c.goal}</span>
                <span className="text-muted-foreground"> +{c.reward} {ui.awe}{c.unlocks ? ui.opens(c.unlocks) : ""}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}

      {tiers.map(({ tier, powers }) => (
        <div key={tier}>
          <h4 className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1.5 flex items-center gap-1">
            {powers[0]?.locked && <Lock className="w-3 h-3" />} {powers[0]?.tier_name}
          </h4>
          <div className="space-y-1">
            {powers.map((p) => (
              <div key={p.id} className={`rounded-md border px-2.5 py-1.5 ${p.locked ? "opacity-45 border-border/50" : open === p.id ? "border-primary/70 ring-1 ring-primary/30" : "border-border/50"}`}>
                <button disabled={p.locked} onClick={() => setOpen(open === p.id ? null : p.id)} className="w-full text-left disabled:cursor-not-allowed">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-[12.5px] font-medium text-foreground">{p.name}</span>
                    <span className={`font-mono text-[11px] ${p.affordable ? "text-primary" : "text-muted-foreground"}`}>{p.cost} {ui.awe}</span>
                  </div>
                  <p className="text-[11px] text-muted-foreground leading-snug">{p.blurb}</p>
                </button>
                {open === p.id && !p.locked && (
                  <PowerForm power={p} game={game} busy={busy} onCast={(args) => { onCast(p.id, args); }} />
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

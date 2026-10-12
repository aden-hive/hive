import { Crown, Dices, Feather, Flame, Moon, ScrollText, Sparkles, Star, Sun, Users } from "lucide-react";
import type { ReactNode } from "react";
import type { ValeCheck, ValeFeedItem, ValePlace, ValeVillager } from "@/api/vale";
import Portrait, { type PersonArt } from "./Portrait";
import { capital, type ValeStrings } from "./strings";

const BAND_COLOR: Record<string, string> = {
  critical: "#5a7254", success: "#8fa889", partial: "#c8a24a", failure: "#9aa4a0", fumble: "#a8352c",
};

/** The d100 cut into its bands (a critical is a fifth of the target; the fumble range overrides all), and where the die fell. */
export function DiceTrack({ check, who, ui, skills }: { check: ValeCheck; who: string; ui: ValeStrings; skills: Record<string, string> }) {
  const cut = (lo: number, hi: number) => Math.max(0, Math.min(hi, check.fumble - 1) - lo + 1);
  const crit = Math.max(1, Math.floor(check.target / 5));
  const zones: [string, number][] = [
    ["critical", cut(1, crit)], ["success", cut(crit + 1, check.target)], ["partial", cut(check.target + 1, check.target + 20)],
    ["failure", cut(check.target + 21, 100)], ["fumble", 101 - check.fumble],
  ];
  const mods = check.mods.map((m) => `${m.mod >= 0 ? "+" : "−"}${Math.abs(m.mod)}`).join(" ");
  return (
    <div className="mt-1.5 space-y-1">
      <div className="relative flex h-2 rounded-sm overflow-hidden" title={ui.rolledAgainst(check.roll, check.target)}>
        {zones.filter(([, w]) => w > 0).map(([band, w]) => <span key={band} style={{ width: `${w}%`, background: BAND_COLOR[band] }} />)}
        <i className="absolute -top-0.5 -bottom-0.5 w-[3px] -ml-[1.5px] bg-foreground ring-1 ring-background" style={{ left: `${check.roll - 0.5}%` }} />
      </div>
      <div className="font-mono text-[10.5px] text-muted-foreground">
        {skills[check.skill] ?? check.skill} · {who} {check.base}{mods ? ` ${mods}` : ""} = {check.target}
        {check.fumble < 96 ? ui.fumblesOn(check.fumble) : ""} · {ui.rolled} <b className="text-foreground">{check.roll}</b> ·{" "}
        <span style={{ color: BAND_COLOR[check.band] }} className="uppercase font-medium">{ui.bands[check.band] ?? check.band}</span>
      </div>
      {check.mods.some((m) => m.why) && (
        <div className="text-[10.5px] text-muted-foreground/80 leading-snug">
          {check.mods.filter((m) => m.why).map((m) => `${m.mod >= 0 ? "+" : "−"}${Math.abs(m.mod)} ${m.why}`).join(" · ")}
        </div>
      )}
    </div>
  );
}

export interface FeedCtx {
  villagers: Record<string, ValeVillager>;
  places: Record<string, ValePlace>;
  onPick: (vid: string) => void;
  ui: ValeStrings;
  waves: string[];
  gods: Record<string, string>;
  skills: Record<string, string>;
  art: Record<string, PersonArt>;
}

type Ctx = FeedCtx;

function Who({ id, ctx }: { id: string; ctx: Ctx }) {
  const v = ctx.villagers[id];
  if (!v) return <span className="font-medium">{id}</span>;
  return (
    <button onClick={() => ctx.onPick(id)} className="inline-flex items-center gap-1 font-medium text-foreground hover:underline">
      <Portrait art={ctx.art[id]} color={v.color} name={v.short} size={16} health={v.health} />
      {v.name}
    </button>
  );
}

function Card({ icon, tone, head, children }: { icon: ReactNode; tone?: string; head: ReactNode; children?: ReactNode }) {
  return (
    <article className="rounded-md border border-border/50 bg-card/40 px-3 py-2" style={tone ? { borderLeft: `3px solid ${tone}` } : undefined}>
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <span className="shrink-0 opacity-80">{icon}</span>
        <span className="min-w-0 truncate">{head}</span>
      </div>
      {children && <div className="mt-1 text-[12.5px] leading-relaxed text-foreground/90 break-words">{children}</div>}
    </article>
  );
}

export function FeedItem({ item, ctx }: { item: ValeFeedItem; ctx: Ctx }) {
  const { ui, gods } = ctx;
  const when = (i: ValeFeedItem) => capital(ui.dayWave(i.day, ctx.waves[i.wave] ?? ""));
  const god = (id: string) => capital(gods[id] ?? id);
  const place = (id: unknown) => (typeof id === "string" && ctx.places[id]?.name) || "";
  const s = (k: string) => String(item[k] ?? "");
  switch (item.type) {
    case "stir": {
      const deeds = (item.deeds as { kind: string; to: string | null; text: string }[]) || [];
      return (
        <Card icon={<Users className="w-3.5 h-3.5" />} head={<><Who id={s("agent")} ctx={ctx} /> · {place(item.place)} · {when(item)}</>}>
          {item.thought ? <p className="italic text-muted-foreground">{s("thought")}</p> : null}
          <ul className="mt-1 space-y-0.5 list-disc pl-4">
            {deeds.map((d, i) => (
              <li key={i}>{d.kind === "speech" ? <>{ui.sayTo(d.to ? ctx.villagers[d.to]?.short ?? d.to : ui.everyone)}“{d.text}”</> : d.text}</li>
            ))}
            {!deeds.length && ((item.done as string[]) || []).map((d, i) => <li key={i}>{d}</li>)}
            {!deeds.length && !((item.done as string[]) || []).length && <li className="list-none -ml-4 text-muted-foreground">{ui.didNothing}</li>}
          </ul>
          {((item.failures as string[]) || []).map((f, i) => <p key={i} className="text-[11px] text-destructive">{f}</p>)}
        </Card>
      );
    }
    case "action":
      return (
        <Card icon={<Users className="w-3.5 h-3.5 animate-pulse" />} head={<><Who id={s("agent")} ctx={ctx} /> · {ui.now}</>}>
          {((item.texts as string[]) || []).join(" ") || s("summary")}
        </Card>
      );
    case "attempt":
    case "undertaking": {
      const check = item.check as ValeCheck | null;
      const title = item.type === "attempt" ? s("what") : s("title");
      return (
        <Card icon={<Dices className="w-3.5 h-3.5" />} tone={BAND_COLOR[s("outcome")] ?? "#9aa4a0"}
          head={<>{item.type === "attempt" ? <Who id={s("agent")} ctx={ctx} /> : ui.undertaking} · {place(item.place)} · {when(item)} · <b className="uppercase">{check ? ui.bands[s("outcome")] ?? s("outcome") : item.outcome === "unattempted" ? ui.nobodyCame : ui.doneNoRoll}</b></>}>
          <p className="font-medium">{title}</p>
          <p>{s("public")}</p>
          {check && <DiceTrack check={check} who={ctx.villagers[check.roller]?.short ?? check.roller} ui={ui} skills={ctx.skills} />}
        </Card>
      );
    }
    case "proposal":
      return (
        <Card icon={<ScrollText className="w-3.5 h-3.5" />} head={<><Who id={s("agent")} ctx={ctx} /> {ui.proposed} · {when(item)}</>}>
          <b>{s("title")}</b>{ui.colon}{s("goal")} <span className="text-muted-foreground">({place(item.site)}{ui.listSep}{ctx.waves[Number(item.when)] ?? ""})</span>
        </Card>
      );
    case "prayer":
      return (
        <Card icon={<Feather className="w-3.5 h-3.5" />} tone={item.to === "overgod" ? "#c8a24a" : undefined}
          head={<><Who id={s("agent")} ctx={ctx} /> {ui.prayedTo(item.to === "overgod" ? ui.you : item.to === "master" ? ui.herMaster : gods[item.to === "ullr" ? "ullr" : "god"] ?? "")} · {when(item)}</>}>
          “{s("text")}”
        </Card>
      );
    case "omen":
      return <Card icon={<Sun className="w-3.5 h-3.5" />} tone={item.by === "overgod" ? "#c8a24a" : "#a8352c"} head={<>{place(item.place) || ui.everywhere} · {when(item)}</>}>{s("text")}</Card>;
    case "dream":
    case "sign":
    case "prophecy":
    case "ledger":
    case "boon": {
      const by = s("by");
      const label = by === "overgod" ? ui.You : gods[by] ? god(by) : by;
      const tone = by === "overgod" ? "#c8a24a" : by === "outer" ? "#6d4fa8" : by === "ullr" ? "#1d7a74" : "#9c7522";
      const what = item.type === "dream" ? <>{ui.dreamFor} <Who id={s("to")} ctx={ctx} /></> : item.type === "sign" ? ui.signAt(place(item.place)) : item.type === "prophecy" ? ui.voice : item.type === "ledger" ? ui.light : ui.boon;
      return <Card icon={<Star className="w-3.5 h-3.5" />} tone={tone} head={<>{label}{ui.colon}{what} · {when(item)}</>}>{s("text")}</Card>;
    }
    case "god":
      return (
        <Card icon={<Sparkles className="w-3.5 h-3.5" />} tone="#9c7522" head={<>{god("god")} · {when(item)}</>}>
          <p className="italic text-muted-foreground">{s("thought")}</p>
        </Card>
      );
    case "star":
      return item.thought ? <Card icon={<Star className="w-3.5 h-3.5" />} tone="#6d4fa8" head={<>{god("outer")} · {when(item)}</>}><p className="italic text-muted-foreground">{s("thought")}</p>{item.public ? <p>{s("public")}</p> : null}</Card> : null;
    case "ullr":
      return <Card icon={<Moon className="w-3.5 h-3.5" />} tone="#1d7a74" head={<>{god("ullr")}{item.awake ? ui.awake : ui.stirringTag} · {when(item)}</>}><p className="italic text-muted-foreground">{s("thought")}</p></Card>;
    case "overgod":
      return <Card icon={<Crown className="w-3.5 h-3.5" />} tone="#c8a24a" head={<>{ui.You} · {s("name")} · −{s("cost")} {ui.awe} · {when(item)}</>}>{s("what")}</Card>;
    case "chapter":
      return <Card icon={<Crown className="w-3.5 h-3.5" />} tone="#c8a24a" head={<>{ui.chapterDone} · {when(item)}</>}><b>{s("title")}</b> · +{s("reward")} {ui.awe}{item.tier ? ui.tierOpen(s("tier")) : ""}</Card>;
    case "awe":
      return <Card icon={<Crown className="w-3.5 h-3.5" />} head={ui.aweDawn(item.day, Number(item.total).toFixed(1), Number(item.prayers) || 0)} />;
    case "night":
      return <Card icon={<Moon className="w-3.5 h-3.5" />} head={ui.night(item.day, Number(item.activations ?? 0), Number(item.checks ?? 0))} />;
    case "error":
      return <Card icon={<Flame className="w-3.5 h-3.5" />} tone="#a8352c" head={ui.wentWrong}>{s("message")}</Card>;
    default:
      return null;
  }
}

export default function ValeFeed({ items, ctx }: { items: ValeFeedItem[]; ctx: Ctx }) {
  return (
    <div className="flex flex-col gap-1.5">
      {items.map((item, i) => <FeedItem key={item.seq ?? `live-${i}`} item={item} ctx={ctx} />)}
      {!items.length && <p className="text-sm text-muted-foreground italic px-1">{ctx.ui.nothingYet}</p>}
    </div>
  );
}

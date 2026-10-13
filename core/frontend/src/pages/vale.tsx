import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { BookOpen, FastForward, Loader2, Pause, Play, Plus, StepForward, Trash2, X } from "lucide-react";
import { ApiError } from "@/api/client";
import {
  valeApi, WAVES,
  type ValeBeat, type ValeChapter, type ValeFeedItem, type ValeGame, type ValeGameSummary, type ValeHostPart, type ValeStory, type ValeVillager, type ValeVillagerDetail,
} from "@/api/vale";
import ValeMap from "@/components/vale/ValeMap";
import ValeFeed, { type FeedCtx } from "@/components/vale/ValeFeed";
import DirectorPanel from "@/components/vale/DirectorPanel";
import HostStage from "@/components/vale/HostStage";
import NovelReader from "@/components/vale/NovelReader";
import Portrait from "@/components/vale/Portrait";
import { VALE_STRINGS, valeStrings, type ValeStrings } from "@/components/vale/strings";

const errorText = (e: unknown) => (e instanceof ApiError ? e.body.error : e instanceof Error ? e.message : String(e));
const pct = (x: number) => `${Math.round(x * 100)}%`;

/** Kept items arrive twice when a fetch and the live stream overlap: keep each seq once, in order, the latest 800. */
function mergeFeed(feed: ValeFeedItem[], items: ValeFeedItem[]): ValeFeedItem[] {
  const seen = new Set(feed.map((i) => i.seq));
  const fresh = items.filter((i) => i.seq != null && !seen.has(i.seq));
  if (!fresh.length) return feed;
  return [...feed, ...fresh].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0)).slice(-800);
}

// The language a new vale is played in, remembered per browser; a Chinese browser starts in Chinese.
const LANG_KEY = "vale.lang";
const STORY_KEY = "vale.story";
const SPEED_KEY = "vale.speed";
function initialLang(): string {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved) return saved;
  } catch { /* storage may be blocked; fall back to the browser's language */ }
  return navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
}

// ---------------------------------------------------------------------------- the list of games

function GameList() {
  const navigate = useNavigate();
  const [games, setGames] = useState<ValeGameSummary[] | null>(null);
  const [stories, setStories] = useState<ValeStory[]>([]);
  const [lang, setLang] = useState(initialLang);
  const [storyId, setStoryId] = useState(() => { try { return localStorage.getItem(STORY_KEY) ?? ""; } catch { return ""; } });
  const [name, setName] = useState("");
  const [days, setDays] = useState("30");
  const [model, setModel] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => { valeApi.list().then((r) => setGames(r.games)).catch((e) => setError(errorText(e))); }, []);
  useEffect(load, [load]);
  useEffect(() => { valeApi.stories().then((r) => setStories(r.stories)).catch((e) => setError(errorText(e))); }, []);

  const story = stories.find((s) => s.id === storyId) ?? stories[0];
  const langs = story ? Object.keys(story.langs) : [lang];
  const chosen = langs.includes(lang) ? lang : langs[0] ?? "en";
  const ui = valeStrings(chosen);
  const pickLang = (l: string) => {
    setLang(l);
    try { localStorage.setItem(LANG_KEY, l); } catch { /* not remembered, still used */ }
  };
  const pickStory = (id: string) => {
    setStoryId(id);
    try { localStorage.setItem(STORY_KEY, id); } catch { /* not remembered, still used */ }
  };

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const settings: Record<string, string> = {};
      if (model.trim()) settings.model = model.trim();
      if (apiBase.trim()) settings.api_base = apiBase.trim();
      const g = await valeApi.create({ name: name.trim() || undefined, story: story?.id, lang: chosen, days: Number(days) || 30, settings });
      navigate(`/vale/${g.id}`);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const field = "bg-muted/30 border border-border/50 rounded-md px-2.5 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40";
  return (
    <div className="max-w-3xl mx-auto px-6 py-8 space-y-8">
      <header className="space-y-2">
        <div className="flex items-start justify-between gap-3">
          <h1 className="text-2xl font-semibold text-foreground whitespace-nowrap">{ui.lobbyTitle}</h1>
          {langs.length > 1 && (
            <div className="flex gap-1 shrink-0" role="group" aria-label={ui.language}>
              {langs.map((l) => (
                <button key={l} onClick={() => pickLang(l)}
                  className={`rounded-full px-2.5 py-0.5 text-[11px] border whitespace-nowrap ${l === chosen ? "bg-foreground text-background border-foreground" : "border-border/60 text-muted-foreground"}`}>
                  {VALE_STRINGS[l]?.langName ?? l}
                </button>
              ))}
            </div>
          )}
        </div>
        <p className="text-sm text-muted-foreground leading-relaxed">{ui.intro}</p>
      </header>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" role="radiogroup" aria-label={ui.world}>
        {stories.map((s) => {
          const h = s.langs[chosen] ?? Object.values(s.langs)[0];
          const on = s.id === story?.id;
          return (
            <button key={s.id} role="radio" aria-checked={on} onClick={() => pickStory(s.id)}
              className={`text-left rounded-lg border p-4 space-y-1.5 transition-colors ${on ? "border-primary bg-primary/5 ring-1 ring-primary/30" : "border-border/60 hover:border-border"}`}>
              <div className="text-base font-semibold text-foreground">{h.title}</div>
              <p className="text-xs text-muted-foreground leading-relaxed">{h.blurb}</p>
            </button>
          );
        })}
      </div>

      <section className="rounded-lg border border-border/60 p-4 space-y-3">
        <h2 className="text-sm font-semibold text-foreground">{ui.newVale}{story ? <span className="font-normal text-muted-foreground">{ui.colon}{(story.langs[chosen] ?? Object.values(story.langs)[0]).title}</span> : null}</h2>
        <div className="grid grid-cols-1 sm:grid-cols-[1fr_7rem] gap-2">
          <input className={field} placeholder={ui.namePlaceholder} value={name} onChange={(e) => setName(e.target.value)} />
          <input className={field} type="number" min={1} max={60} value={days} onChange={(e) => setDays(e.target.value)} title={ui.daysTitle} />
        </div>
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">{ui.modelSummary}</summary>
          <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
            <input className={field} placeholder={ui.modelPlaceholder} value={model} onChange={(e) => setModel(e.target.value)} />
            <input className={field} placeholder={ui.apiBasePlaceholder} value={apiBase} onChange={(e) => setApiBase(e.target.value)} />
          </div>
          <p className="mt-1.5">{ui.modelNote}</p>
        </details>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <button onClick={create} disabled={busy}
          className="rounded-md bg-primary text-primary-foreground text-sm font-medium px-3 py-1.5 flex items-center gap-1.5 disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} {ui.begin}
        </button>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-foreground">{ui.yourVales}</h2>
        {games === null ? <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
          : !games.length ? <p className="text-sm text-muted-foreground italic">{ui.noneYet}</p>
          : games.map((g) => (
            <div key={g.id} className="flex items-center gap-3 rounded-md border border-border/50 px-3 py-2">
              <button className="flex-1 text-left" onClick={() => navigate(`/vale/${g.id}`)}>
                <div className="text-sm font-medium text-foreground">
                  {g.name} <span className="ml-1 text-[10px] font-normal text-muted-foreground">{VALE_STRINGS[g.lang]?.langName ?? g.lang}</span>
                </div>
                <div className="text-[11px] text-muted-foreground font-mono">
                  {g.clock ? ui.dayWave(g.clock.day, (g.waves ?? WAVES)[g.clock.wave]) : ui.notBegun} {ui.ofDays(g.days)} · {ui.status[g.status] ?? g.status} · {g.created}
                </div>
              </button>
              <button title={ui.remove} className="text-muted-foreground hover:text-destructive"
                onClick={async () => { if (confirm(ui.confirmRemove(g.name))) { await valeApi.remove(g.id); load(); } }}>
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------- one villager, fully

function VillagerDrawer({ game, villager, ui, onClose }: { game: ValeGame; villager: ValeVillager; ui: ValeStrings; onClose: () => void }) {
  const [detail, setDetail] = useState<ValeVillagerDetail | null>(null);
  useEffect(() => { valeApi.villager(game.id, villager.id).then(setDetail).catch(() => setDetail(null)); }, [game.id, villager.id]);
  return (
    <aside className="fixed right-0 top-0 bottom-0 w-full sm:w-[420px] z-40 bg-background border-l border-border shadow-xl overflow-y-auto">
      <div className="p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{villager.role}</div>
            <h2 className="text-lg font-semibold text-foreground flex items-center gap-2.5">
              <Portrait art={game.art?.people?.[villager.id]} color={villager.color} name={villager.short} size={52} health={villager.health} />{villager.name}
            </h2>
            <div className="text-xs text-muted-foreground">
              {ui.health[villager.health]}{villager.mood ? ` · ${villager.mood}` : ""} · {ui.energy} {villager.reserve.toFixed(1)}
            </div>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground"><X className="w-4 h-4" /></button>
        </div>
        <p className="text-sm text-foreground/85">{/[.!?。！？]$/.test(villager.public) ? villager.public : villager.public + ui.stop}</p>
        {detail?.deeper && (
          <div className="border-l-2 border-primary/60 pl-3">
            <div className="text-[11px] uppercase tracking-wider text-primary">{ui.secret}</div>
            <p className="text-[12.5px] text-foreground/85 leading-relaxed">{detail.deeper.replace(/\s*\n\s*/g, game.lang === "en" ? " " : "")}</p>
          </div>
        )}
        <div>
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">{ui.sheet}</div>
          <div className="grid grid-cols-3 gap-x-3 gap-y-0.5 font-mono text-[11px]">
            {Object.entries(villager.skills).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <span key={k} className={v >= 70 ? "text-foreground" : "text-muted-foreground"}>{game.skills[k] ?? k} {v}</span>
            ))}
          </div>
        </div>
        <div className="text-xs text-muted-foreground">
          {ui.carries}{ui.colon}{Object.entries(villager.items).map(([k, v]) => `${game.goods[k] ?? k} ×${v}`).join(ui.listSep) || ui.nothing}
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">{ui.notesNow}</div>
          <p className="text-[12.5px] whitespace-pre-wrap text-foreground/90 bg-muted/20 rounded-md p-2.5">{villager.memory || ui.empty}</p>
        </div>
        {detail?.rules?.length ? (
          <div>
            <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">{ui.rules}</div>
            <ul className="list-disc pl-4 text-[12px] text-foreground/85 space-y-0.5">{detail.rules.map((r, i) => <li key={i}>{r}</li>)}</ul>
          </div>
        ) : null}
        {detail?.history?.length ? (
          <details>
            <summary className="text-[11px] uppercase tracking-wider text-muted-foreground cursor-pointer">{ui.history}</summary>
            <div className="mt-2 space-y-2">
              {detail.history.slice().reverse().map((h) => (
                <div key={h.day} className="text-[12px]"><span className="font-mono text-muted-foreground">{ui.day(h.day)}</span>
                  <p className="whitespace-pre-wrap text-foreground/80">{h.text}</p></div>
              ))}
            </div>
          </details>
        ) : null}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------- a game

function TruthPanel({ game, ui }: { game: ValeGame; ui: ValeStrings }) {
  const { panel, weather } = game.truth;
  const tone = (t?: string) => (t === "bad" ? "text-destructive" : t === "good" ? "text-primary" : "text-foreground");
  return (
    <div className="rounded-lg border border-border/60 p-3 space-y-2 text-xs">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{ui.onlyYou}</div>
      {panel.facts.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-foreground/90">
          {panel.facts.map((f, i) => (
            <span key={i}>{f.label}{f.text ? <>{ui.colon}<b className={tone(f.tone)}>{f.text}</b></> : null}</span>
          ))}
        </div>
      )}
      {panel.bars.length > 0 && (
        <div className="grid grid-cols-[auto_1fr_auto] gap-x-2 gap-y-1 items-center">
          {panel.bars.map((b, i) => (
            <div key={i} className="contents">
              <span className="text-muted-foreground">{b.label}</span>
              <div className="h-1.5 rounded bg-muted overflow-hidden">
                <div className="h-full" style={{ width: pct(Math.max(0, Math.min(1, b.value))), background: b.tone === "bad" ? "#a8352c" : b.tone === "good" ? "#5a8f6a" : "#8a7a52" }} />
              </div>
              <span className="font-mono text-[10.5px] text-muted-foreground">{b.text ?? pct(b.value)}</span>
            </div>
          ))}
        </div>
      )}
      {weather && <p className="text-muted-foreground italic">{weather}</p>}
    </div>
  );
}

function GameView({ gameId }: { gameId: string }) {
  const navigate = useNavigate();
  const [game, setGame] = useState<ValeGame | null>(null);
  const [snaps, setSnaps] = useState<Record<string, ValeGame>>({});
  const [feed, setFeed] = useState<ValeFeedItem[]>([]);
  const [live, setLive] = useState<ValeFeedItem[]>([]);
  const [stirred, setStirred] = useState<Set<string>>(new Set());
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "people" | "gods" | "dice">("all");
  const [tab, setTab] = useState<"stage" | "record" | "novel">("stage");
  const [chapters, setChapters] = useState<ValeChapter[]>([]);
  const [writing, setWriting] = useState<number[]>([]);
  const [chapterDay, setChapterDay] = useState<number | null>(null);
  const [fresh, setFresh] = useState<{ day: number; title: string } | null>(null);
  const [speed, setSpeedState] = useState(() => { try { return localStorage.getItem(SPEED_KEY) || "normal"; } catch { return "normal"; } });
  const [paused, setPaused] = useState(false);
  const [autoplay, setAutoplay] = useState(false);
  const [playing, setPlaying] = useState<ValeHostPart | null>(null);
  const [power, setPower] = useState<string | null>(null);
  const [startAt, setStartAt] = useState<number | null>(null);
  const lastSeq = useRef(0);
  const asked = useRef(false); // a part has been asked for and the vale has not answered yet

  const refresh = useCallback(async () => {
    try {
      const g = await valeApi.get(gameId);
      setGame(g);
      setSnaps((s) => ({ ...s, [`${g.last.day}-${g.last.wave}`]: g }));
      const { items } = await valeApi.feed(gameId, lastSeq.current, 2000);
      if (items.length) {
        lastSeq.current = Math.max(lastSeq.current, items[items.length - 1].seq ?? 0);
        setFeed((f) => mergeFeed(f, items));
      }
      return items;
    } catch (e) {
      setError(errorText(e));
      return [];
    }
  }, [gameId]);

  const loadNovel = useCallback(async () => {
    try {
      const r = await valeApi.novel(gameId);
      setChapters(r.chapters);
      setWriting(r.writing);
    } catch (e) {
      setError(errorText(e));
    }
  }, [gameId]);

  useEffect(() => {
    lastSeq.current = 0;
    setFeed([]);
    void loadNovel();
    // Whatever was told before the page opened is shown, not replayed.
    void refresh().then((items) => setStartAt(items.filter((i) => i.type === "host").length));
    let unsub: (() => void) | null = null;
    void valeApi.watch(gameId, (item) => {
      if (item.seq) {
        lastSeq.current = Math.max(lastSeq.current, item.seq);
        setFeed((f) => mergeFeed(f, [item]));
        if (item.type === "stir") setLive((l) => l.filter((x) => x.agent !== item.agent));
      } else if (item.type === "action") {
        setLive((l) => [...l, item].slice(-30));
      } else if (item.type === "stirred") {
        setStirred(new Set(item.agents as string[]));
      } else if (item.type === "state") {
        asked.current = false;
        setStirred(new Set());
        setLive([]);
        void refresh();
      } else if (item.type === "phase") {
        setGame((g) => (g ? { ...g, phase: String(item.phase ?? ""), status: item.phase ? "running" : g.status } : g));
      } else if (item.type === "novel_writing") {
        setWriting((w) => (w.includes(item.day) ? w : [...w, item.day]));
      } else if (item.type === "novel") {
        setWriting((w) => w.filter((d) => d !== item.day));
        setFresh({ day: item.day, title: String(item.title ?? "") });
        void loadNovel();
      } else if (item.type === "novel_error") {
        setWriting((w) => w.filter((d) => d !== item.day));
        setError(String(item.message ?? "error"));
      } else if (item.type === "error") {
        asked.current = false;
        setAutoplay(false);
        setError(String(item.message ?? "error"));
      }
    }).then((u) => { unsub = u; });
    return () => { unsub?.(); };
  }, [gameId, refresh, loadNovel]);

  const parts = useMemo<ValeHostPart[]>(
    () => feed.filter((i) => i.type === "host").map((i) => ({ seq: i.seq ?? 0, day: i.day, wave: i.wave, title: String(i.title ?? ""), beats: (i.beats as ValeBeat[]) ?? [] })),
    [feed],
  );
  // The map and the panels show the vale as the host has told it so far, never ahead of the story.
  const shown = (playing && snaps[`${playing.day}-${playing.wave}`]) || game;

  // Autoplay asks for the next part as soon as the last one starts playing: the vale works while you watch.
  const unstarted = playing ? parts.length - 1 - parts.findIndex((p) => p.seq === playing.seq) : 0;
  useEffect(() => {
    if (!autoplay || !game || asked.current || game.status !== "idle" || unstarted > 0) return;
    asked.current = true;
    valeApi.advance(gameId, 1).catch((e) => { asked.current = false; setAutoplay(false); setError(errorText(e)); });
  }, [autoplay, game, unstarted, gameId]);
  useEffect(() => { if (game?.status === "finished") setAutoplay(false); }, [game?.status]);

  const setSpeed = (s: string) => { setSpeedState(s); try { localStorage.setItem(SPEED_KEY, s); } catch { /* not remembered */ } };
  const onPlaying = useCallback((p: ValeHostPart | null) => setPlaying(p), []);
  const ui = valeStrings(game?.lang);
  const ctx = useMemo<FeedCtx>(() => ({
    villagers: Object.fromEntries((game?.villagers ?? []).map((v) => [v.id, v])),
    places: Object.fromEntries((game?.places ?? []).map((p) => [p.id, p])),
    onPick: (vid: string) => setPicked(vid),
    ui: valeStrings(game?.lang),
    waves: game?.waves ?? WAVES,
    gods: game?.gods ?? {},
    skills: game?.skills ?? {},
    art: game?.art?.people ?? {},
  }), [game]);

  const record = useMemo(() => {
    const kinds: Record<string, string[]> = {
      people: ["stir", "proposal", "prayer"],
      gods: ["god", "star", "ullr", "dream", "sign", "prophecy", "ledger", "boon", "overgod", "chapter", "awe"],
      dice: ["attempt", "undertaking"],
    };
    const all = feed.filter((i) => i.type !== "host" && !i.private);
    return (filter === "all" ? all : all.filter((i) => kinds[filter].includes(i.type))).slice(-400).reverse();
  }, [feed, filter]);

  const marks = useMemo(() => {
    if (!shown) return [];
    const { day, wave } = shown.last;
    return feed.filter((i) => (i.type === "omen" || i.type === "sign") && i.place && !i.private && i.day === day && i.wave <= wave).slice(-6);
  }, [feed, shown]);

  const go = async (fn: () => Promise<unknown>) => {
    setError(null);
    try { await fn(); await refresh(); } catch (e) { setError(errorText(e)); }
  };
  const cast = async (p: string, args: Record<string, unknown>) => {
    setBusy(true);
    await go(async () => { const r = await valeApi.act(gameId, p, args); setGame(r.game); setPower(null); });
    setBusy(false);
  };
  const openPower = (p: string) => {
    setPower(p);
    document.getElementById("vale-director")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  if (!game || !shown) return <div className="p-8"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>;
  const running = game.status === "running";
  const finished = game.status === "finished";
  const btn = "rounded-md border border-border/60 px-2.5 py-1 text-xs flex items-center gap-1.5 whitespace-nowrap hover:bg-muted/40 disabled:opacity-40";
  const pickedVillager = picked ? shown.villagers.find((v) => v.id === picked) : undefined;

  return (
    <div className="h-full overflow-y-auto" lang={game.lang}>
      <div className="max-w-[1500px] mx-auto px-4 py-4 space-y-3">
        <header className="flex flex-wrap items-center gap-3">
          <button className="text-xs text-muted-foreground hover:text-foreground" onClick={() => navigate("/vale")}>{ui.back}</button>
          <h1 className="text-lg font-semibold text-foreground">{game.name}</h1>
          <span className="font-mono text-xs text-muted-foreground">
            {finished ? ui.over : ui.next(game.clock.day, game.waves[game.clock.wave])} / {ui.days(game.days)}
          </span>
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            <button className={btn} disabled={running || finished || autoplay} onClick={() => go(() => valeApi.advance(gameId, 1))}><StepForward className="w-3.5 h-3.5" />{ui.nextPart}</button>
            <button className={btn} disabled={running || finished || autoplay}
              onClick={() => go(() => valeApi.advance(gameId, 6 - game.clock.wave))}><FastForward className="w-3.5 h-3.5" />{ui.toDawn}</button>
            {autoplay
              ? <button className={btn} onClick={() => setAutoplay(false)}><Pause className="w-3.5 h-3.5" />{ui.pause}</button>
              : <button className={btn} disabled={finished} onClick={() => { setPaused(false); setAutoplay(true); }}><Play className="w-3.5 h-3.5" />{ui.autoplay}</button>}
          </div>
        </header>
        {error && <p className="text-xs text-destructive">{error}</p>}

        <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_320px] gap-4 items-start">
          <div className="min-w-0 space-y-2">
            <div className="flex gap-1">
              {(["stage", "novel", "record"] as const).map((x) => (
                <button key={x} onClick={() => { setTab(x); if (x === "novel") setFresh(null); }}
                  className={`relative rounded-full px-3 py-0.5 text-[12px] border ${tab === x ? "bg-foreground text-background border-foreground" : "border-border/60 text-muted-foreground"}`}>
                  {x === "stage" ? ui.tabStage : x === "novel" ? ui.tabNovel : ui.tabRecord}
                  {x === "novel" && (fresh || writing.length > 0) && <span className={`absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full ${fresh ? "bg-primary" : "bg-primary/50 animate-pulse"}`} />}
                </button>
              ))}
            </div>
            {tab === "stage" && fresh && (
              <button onClick={() => { setTab("novel"); setChapterDay(fresh.day); setFresh(null); }}
                className="w-full flex items-center gap-2 rounded-lg border border-primary/50 bg-primary/5 px-3 py-2 text-left text-[13px] hover:bg-primary/10">
                <BookOpen className="w-4 h-4 text-primary shrink-0" />
                <span className="flex-1 text-foreground">{ui.chapterReady(fresh.day, fresh.title)}</span>
                <span className="text-primary font-medium">{ui.read} →</span>
              </button>
            )}
            {tab === "novel" && (
              <NovelReader game={game} chapters={chapters} writing={writing} day={chapterDay} onDay={setChapterDay} ui={ui}
                onWrite={(d) => go(async () => { await valeApi.writeChapter(gameId, d); setWriting((w) => [...w, d]); })} />
            )}
            <div className={tab === "stage" ? "" : "hidden"}>
              {startAt !== null && (
                <HostStage game={shown} parts={parts} startAt={startAt} ui={ui} speed={speed} paused={paused} running={running}
                  phase={game.phase} live={live} onSpeed={setSpeed} onPause={setPaused} onPlaying={onPlaying} onPower={openPower} />
              )}
            </div>
            {tab === "record" && (
              <div className="space-y-2">
                <div className="flex gap-1">
                  {(["all", "people", "gods", "dice"] as const).map((f) => (
                    <button key={f} onClick={() => setFilter(f)}
                      className={`rounded-full px-2.5 py-0.5 text-[11px] border ${filter === f ? "bg-foreground text-background border-foreground" : "border-border/60 text-muted-foreground"}`}>{ui.filters[f]}</button>
                  ))}
                </div>
                <div className="max-h-[78vh] overflow-y-auto pr-1">
                  <ValeFeed items={record} ctx={ctx} />
                </div>
              </div>
            )}
          </div>

          <div className="space-y-3 min-w-0">
            <ValeMap places={shown.places} villagers={shown.villagers} scene={shown.truth.scene} art={game.art ?? {}} stirred={stirred} marks={marks} onPick={setPicked}
              title={game.story.title || game.name} ui={ui} />
            <TruthPanel game={shown} ui={ui} />
            {shown.undertakings.length > 0 && (
              <div className="rounded-lg border border-border/60 p-3 text-xs space-y-1">
                <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{ui.waiting}</div>
                {shown.undertakings.map((u) => (
                  <div key={u.id}><b className="text-foreground">{u.title}</b> <span className="text-muted-foreground">
                    · {ctx.places[u.site]?.name} · {ui.dayWave(u.due_day, game.waves[u.when])} · {u.supporters.map((s) => ctx.villagers[s]?.short ?? s).join(ui.listSep)}</span></div>
                ))}
              </div>
            )}
            <div className="flex flex-wrap gap-1.5">
              {shown.villagers.map((v) => (
                <button key={v.id} onClick={() => setPicked(v.id)} title={v.role}
                  className="flex items-center gap-1 rounded-full border border-border/50 pl-0.5 pr-2 py-0.5 text-[11px] hover:bg-muted/40">
                  <Portrait art={game.art?.people?.[v.id]} color={v.color} name={v.short} size={20} health={v.health} />{v.short}
                  {v.health ? <span className={v.health >= 2 ? "text-destructive" : "text-primary"}>•</span> : null}
                </button>
              ))}
            </div>
          </div>

          <div id="vale-director" className="lg:col-span-2 xl:col-span-1 xl:sticky xl:top-2 xl:max-h-[90vh] overflow-y-auto pr-1">
            <DirectorPanel game={game} busy={busy} error={null} onCast={cast} open={power} onOpen={setPower} />
          </div>
        </div>
      </div>
      {pickedVillager && <VillagerDrawer game={shown} villager={pickedVillager} ui={ui} onClose={() => setPicked(null)} />}
    </div>
  );
}

export default function ValePage() {
  const { gameId } = useParams<{ gameId?: string }>();
  return gameId ? <GameView key={gameId} gameId={gameId} /> : <GameList />;
}

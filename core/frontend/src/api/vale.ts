/**
 * The vale game (framework/apps/vale on the runtime): a village of fifteen Hive agents,
 * played as the god beyond gods. See core/framework/apps/vale/routes.py for the API.
 */

import { api, subscribeSse } from "./client";
import type { PersonArt } from "@/components/vale/Portrait";
import type { PlaceArt } from "@/components/vale/SceneArt";

/** Where a story's painted pictures are served from. */
export const artBase = (story: string) => `${import.meta.env.VITE_API_BASE ?? "/api"}/vale/art/${encodeURIComponent(story)}`;

/** The parts of the day in English, for a game that does not name its own. */
export const WAVES = ["dawn", "morning", "midday", "afternoon", "dusk", "night"];

export interface ValeClock {
  day: number;
  wave: number;
}

export interface ValePlace {
  id: string;
  name: string;
  desc: string;
  x: number;
  y: number;
  roads: string[];
}

export interface ValeVillager {
  id: string;
  name: string;
  short: string;
  role: string;
  public: string;
  color: string;
  loc: string | null;
  travel: { to: string; from: string; arrive: number } | null;
  health: number;
  mood: string;
  reserve: number;
  items: Record<string, number>;
  skills: Record<string, number>;
  recent: string[];
  memory: string;
  confined: number;
}

export interface ValePowerParam {
  name: string;
  kind: "person" | "place" | "text" | "god" | "days";
  label: string;
}

export interface ValePower {
  id: string;
  tier: number;
  tier_name: string;
  cost: number;
  name: string;
  blurb: string;
  params: ValePowerParam[];
  locked: boolean;
  affordable: boolean;
}

export interface ValeChapter {
  id: string;
  title: string;
  goal: string;
  reward: number;
  unlocks: string | null;
  status: "done" | "current" | "later";
}

export interface ValeOvergod {
  awe: number;
  cap: number;
  tier: number;
  tier_name: string;
  chapters: ValeChapter[];
  powers: ValePower[];
  known_by: string[];
  revealed: string[];
  written: string[];
  decrees: Record<string, { text: string; until: number }>;
  income: { day: number; base: number; prayers: number; drama: number; total: number }[];
}

/** What only the player sees, as the world's rules declare it (rules.toml [panel]). */
export interface ValePanel {
  facts: { label: string; text?: string; tone?: string }[];
  bars: { label: string; value: number; text?: string; tone?: string }[];
}

/** What the pictures need, as the world's rules declare it (rules.toml [scene]). */
export interface ValeScene {
  /** How troubled each place's water is, 0 to 1. */
  water: Record<string, number>;
  /** How brightly each place glows (a lit lighthouse, lanterns strung), 0 to 1. */
  glow: Record<string, number>;
  /** The world's own marks the pictures know (a deep door open, a stone standing, a hard winter). */
  marks: Record<string, unknown>;
}

export interface ValeTruth {
  weather: string;
  weather_kind: string;
  panel: ValePanel;
  scene: ValeScene;
}

export interface ValeGame {
  id: string;
  name: string;
  /** The language the vale is played in: its villagers, gods and this page all use it. */
  lang: string;
  story: { id: string; title: string; blurb: string };
  /** The parts of the day, in the game's language. */
  waves: string[];
  /** What the story calls its gods: god, outer, ullr, overgod. */
  gods: Record<string, string>;
  /** Skill ids to their names, and goods ids to theirs, in the game's language. */
  skills: Record<string, string>;
  goods: Record<string, string>;
  /** How the story draws its people and places. */
  art: ValeArt;
  days: number;
  status: "idle" | "running" | "finished";
  phase: string;
  autoplay: boolean;
  clock: ValeClock;
  last: ValeClock;
  places: ValePlace[];
  villagers: ValeVillager[];
  truth: ValeTruth;
  ledger: string;
  undertakings: { id: string; title: string; site: string; when: number; due_day: number; supporters: string[] }[];
  overgod: ValeOvergod;
  queue: { power: string; args: Record<string, unknown> }[];
  usage: Record<string, number>;
  settings: Record<string, string>;
}

export interface ValeGameSummary {
  id: string;
  name: string;
  story: string;
  lang: string;
  waves: string[];
  created: string;
  days: number;
  clock: ValeClock | null;
  status: string;
}

export interface ValeCheck {
  skill: string;
  roller: string;
  base: number;
  mods: { why: string; mod: number }[];
  target: number;
  fumble: number;
  roll: number;
  band: "critical" | "success" | "partial" | "failure" | "fumble";
}

/** One thing that happened, as the feed shows it. `seq` is set on kept items; live ones carry `live`. */
export interface ValeFeedItem {
  seq?: number;
  live?: boolean;
  type: string;
  day: number;
  wave: number;
  [key: string]: unknown;
}

/** One roll as the host plays it: the real check, who rolled, what for, and what it brought. */
export interface ValeHostRoll {
  ref: string;
  kind: string;
  what: string;
  who: string;
  roller: string;
  place: string | null;
  outcome: string;
  public: string;
  check: ValeCheck;
}

/** One beat of the host's script: the table plays them one at a time. */
export interface ValeBeat {
  kind: "open" | "scene" | "roll" | "aside" | "turn";
  text?: string;
  place?: string | null;
  who?: string[] | string;
  before?: string;
  after?: string;
  roll?: ValeHostRoll;
  powers?: string[];
}

export interface ValeHostPart {
  seq: number;
  day: number;
  wave: number;
  title: string;
  beats: ValeBeat[];
}

/** One day of the novel the host writes after each night. */
export interface ValeChapter {
  day: number;
  title: string;
  text: string;
  scenes: { place: string; pov: string; when: string }[];
}

/** How a world is drawn: its people, its places, its map (art.toml). */
export interface ValeArt {
  people?: Record<string, PersonArt>;
  places?: Record<string, PlaceArt>;
  map?: {
    /** The land's outline, for an island; the rest of the map is sea. */
    coast?: [number, number][];
    /** Streams: points [owner place, x, y]; each stretch is coloured by its owner's water. */
    streams?: { points: [string, number, number][] }[];
    /** Where a stream spills in flood, coloured by its owner's water. */
    floods?: { owner: string; points: [number, number][] }[];
  };
  /** The picture for openings: "vale" (hills and a river) or "isle" (sea and an island). */
  panorama?: string;
}

export interface ValeStory {
  id: string;
  /** Each language the story is written in, with its title and blurb in that language. */
  langs: Record<string, { title: string; blurb: string }>;
}

export interface ValeVillagerDetail {
  id: string;
  persona: string;
  want: string;
  deeper: string;
  rules: string[];
  history: { day: number; text: string }[];
  knows: string[];
}

export const valeApi = {
  stories: () => api.get<{ stories: ValeStory[] }>("/vale/stories"),
  list: () => api.get<{ games: ValeGameSummary[] }>("/vale/games"),
  create: (body: { name?: string; story?: string; lang?: string; days?: number; seed?: number; settings?: Record<string, string> }) =>
    api.post<ValeGame>("/vale/games", body),
  get: (id: string) => api.get<ValeGame>(`/vale/games/${encodeURIComponent(id)}`),
  remove: (id: string) => api.delete<{ deleted: string }>(`/vale/games/${encodeURIComponent(id)}`),
  feed: (id: string, after = 0, limit = 400) =>
    api.get<{ items: ValeFeedItem[] }>(`/vale/games/${encodeURIComponent(id)}/feed?after=${after}&limit=${limit}`),
  advance: (id: string, waves: number) => api.post<{ running: boolean }>(`/vale/games/${encodeURIComponent(id)}/advance`, { waves }),
  autoplay: (id: string, on: boolean) => api.post<{ autoplay: boolean }>(`/vale/games/${encodeURIComponent(id)}/autoplay`, { on }),
  act: (id: string, power: string, args: Record<string, unknown>) =>
    api.post<{ result: Record<string, unknown>; game: ValeGame }>(`/vale/games/${encodeURIComponent(id)}/act`, { power, args }),
  novel: (id: string) => api.get<{ chapters: ValeChapter[]; writing: number[] }>(`/vale/games/${encodeURIComponent(id)}/novel`),
  writeChapter: (id: string, day: number) => api.post<{ writing: number }>(`/vale/games/${encodeURIComponent(id)}/novel/${day}`, {}),
  villager: (id: string, vid: string) =>
    api.get<ValeVillagerDetail>(`/vale/games/${encodeURIComponent(id)}/villagers/${encodeURIComponent(vid)}`),
  /** Live events; returns the unsubscribe function. */
  watch: (id: string, onItem: (item: ValeFeedItem) => void) =>
    subscribeSse(
      `/vale/games/${encodeURIComponent(id)}/events`,
      {
        onEvent: (_event, data) => {
          try {
            onItem(JSON.parse(data) as ValeFeedItem);
          } catch {
            /* a malformed frame is skipped; the next state refresh catches up */
          }
        },
      },
      { silentConnectivity: true },
    ),
};

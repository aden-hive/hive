/**
 * A persona's text (profile.yaml `core_traits`) cut into the chapters it is written in, and put back
 * together byte for byte: a chapter keeps the exact slice of the text it came from, and only an edited
 * chapter is rebuilt, in the style it was written.
 *
 * - "block": starts with `<tag>` at the start of a line (its text may follow on the same line) and runs
 *   to its `</tag>`; without one, to the next chapter. Tags inside a closed block stay inside it.
 * - "marker": a `# <<<NAME>>>` line, such as the bounds of the tunable voice.
 * - "text": anything between them; whitespace-only stretches are kept so the text joins back as it was.
 */

export type Chapter = {
  kind: "block" | "text" | "marker";
  /** block: the tag; marker: the marker's name. */
  tag?: string;
  title: string;
  /** What the editor shows: the inside of a block, or the text itself. */
  body: string;
  /** The slice of the original text this chapter is (joining puts it back). */
  raw: string;
  /** How a block was written, so an edit keeps it: indent, text on the tag's line, closing tag and its place. */
  style?: { indent: string; inlineOpen: boolean; closed: boolean; inlineClose: boolean; tail: string };
};

const START_RE = /^([ \t]*)<([a-z][a-z0-9_]*)>/;
const MARKER_RE = /^[ \t]*#\s*<<<([A-Za-z0-9_]+)>>>[ \t]*$/;

const TITLES: Record<string, string> = {
  voice_fewshot: "Voice examples",
  anti_ai_blocklist: "Never says",
  self_as_instinct: "Self, as instinct",
  hard_invariants: "Hard invariants",
};

export function chapterTitle(tag: string): string {
  if (TITLES[tag]) return TITLES[tag];
  const words = tag.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The title of a stretch of text whose first line doesn't read as one. */
const UNTITLED = "Notes";

function textTitle(body: string): string {
  const first = (body.split("\n").find((l) => l.trim()) ?? "").trim();
  // A heading set in bold reads the same as one without it.
  const line = first.replace(/^(\*\*|__)(.+)\1$/, "$2").trim();
  const bracket = /^\[(.+)\]$/.exec(line);
  if (bracket) return bracket[1];
  if (line.startsWith("#")) return line.replace(/^#+\s*/, "");
  // A short line ending in a colon introduces what follows: "Two occasions, handled the other way round:".
  const lead = /^(.{1,40}?)\s*[:：]$/.exec(line);
  if (lead) return lead[1];
  return UNTITLED;
}

/** A stretch of text whose first line doesn't read as a title. */
export function isUntitled(chapter: Chapter): boolean {
  return chapter.kind === "text" && chapter.title === UNTITLED;
}

/** A chapter's name in a list of them: its title, or how an untitled stretch of text begins. */
export function chapterLabel(chapter: Chapter): string {
  if (!isUntitled(chapter)) return chapter.title;
  const first = Array.from(chapter.body.trim().split("\n")[0]);
  return first.length > 18 ? `${first.slice(0, 18).join("")}…` : first.join("");
}

/** What a reader sees of a chapter's text: a stretch of text titled by its first line doesn't repeat it. */
export function readingBody(chapter: Chapter): string {
  if (chapter.kind !== "text" || isUntitled(chapter)) return chapter.body;
  return chapter.body.replace(/^[^\n]*\n?/, "").replace(/^\n+/, "");
}

function trimNewlines(s: string): string {
  return s.replace(/^\n+/, "").replace(/\s+$/, "");
}

/** Line starts in ``text`` from ``from``: [offset, line] pairs. */
function linesFrom(text: string, from: number): [number, string][] {
  const out: [number, string][] = [];
  let at = from;
  while (at < text.length) {
    const nl = text.indexOf("\n", at);
    const end = nl === -1 ? text.length : nl;
    out.push([at, text.slice(at, end)]);
    at = end + 1;
  }
  return out;
}

function cutText(slice: string, out: Chapter[]): void {
  if (!slice) return;
  let buffer = "";
  const flush = () => {
    if (buffer) out.push({ kind: "text", title: textTitle(buffer), body: trimNewlines(buffer), raw: buffer });
    buffer = "";
  };
  for (const line of slice.split(/(?<=\n)/)) {
    const marker = MARKER_RE.exec(line.replace(/\n$/, ""));
    if (marker) {
      flush();
      out.push({ kind: "marker", tag: marker[1], title: marker[1], body: "", raw: line });
    } else {
      buffer += line;
    }
  }
  flush();
}

export function parseChapters(text: string): Chapter[] {
  const out: Chapter[] = [];
  let pos = 0;
  let textStart = 0;
  while (pos < text.length) {
    const next = linesFrom(text, pos).find(([, line]) => START_RE.test(line));
    if (!next) break;
    const [start, line] = next;
    const [, indent, tag] = START_RE.exec(line)!;
    const afterTag = start + indent.length + tag.length + 2;
    const closeAt = text.indexOf(`</${tag}>`, afterTag);
    // Without its closing tag, a block runs to the next chapter (block or marker).
    const nextStart = linesFrom(text, afterTag)
      .slice(1)
      .find(([, l]) => START_RE.test(l) || MARKER_RE.test(l))?.[0];
    const closed = closeAt !== -1 && (nextStart === undefined || closeAt < nextStart || !isOwnChapter(text, nextStart, closeAt));
    let end: number;
    let inner: string;
    let inlineClose = false;
    let tail = "";
    if (closed) {
      end = closeAt + tag.length + 3;
      inner = text.slice(afterTag, closeAt);
      inlineClose = !/\n[ \t]*$/.test(inner);
    } else {
      end = nextStart ?? text.length;
      const rawInner = text.slice(afterTag, end);
      tail = /\s*$/.exec(rawInner)?.[0] ?? "";
      inner = rawInner.slice(0, rawInner.length - tail.length);
    }
    cutText(text.slice(textStart, start), out);
    const inlineOpen = !inner.startsWith("\n");
    out.push({
      kind: "block",
      tag,
      title: chapterTitle(tag),
      body: trimNewlines(inlineOpen ? inner.replace(/^[ \t]/, "") : inner),
      raw: text.slice(start, end),
      style: { indent, inlineOpen, closed, inlineClose, tail },
    });
    pos = end;
    textStart = end;
  }
  cutText(text.slice(textStart), out);
  return out;
}

/** Whether the tag starting at ``at`` begins a chapter of its own rather than sitting inside one closing at ``closeAt``. */
function isOwnChapter(text: string, at: number, closeAt: number): boolean {
  const eol = text.indexOf("\n", at);
  const match = START_RE.exec(text.slice(at, eol === -1 ? undefined : eol));
  if (!match) return true;
  const innerClose = text.indexOf(`</${match[2]}>`, at);
  // A nested block closes before its parent does; anything else starts a chapter of its own.
  return innerClose === -1 || innerClose > closeAt;
}

/** The chapter with a new body, rebuilt in the style it was written. */
export function withBody(chapter: Chapter, body: string): Chapter {
  const clean = trimNewlines(body.replace(/\r\n/g, "\n"));
  if (chapter.kind === "block" && chapter.style) {
    const { indent, inlineOpen, closed, inlineClose, tail } = chapter.style;
    const open = `${indent}<${chapter.tag}>${inlineOpen ? " " : "\n"}${clean}`;
    const close = closed ? `${inlineClose ? " " : `\n${indent}`}</${chapter.tag}>` : tail;
    return { ...chapter, body: clean, raw: open + close };
  }
  if (chapter.kind === "text") {
    const lead = /^\n*/.exec(chapter.raw)?.[0] ?? "";
    const tail = /\s*$/.exec(chapter.raw)?.[0] ?? "";
    return { ...chapter, body: clean, title: textTitle(clean), raw: `${lead}${clean}${tail}` };
  }
  return chapter;
}

export function joinChapters(chapters: Chapter[]): string {
  return chapters.map((c) => c.raw).join("");
}

/** Chapters worth showing: blocks, markers, and text that says something. */
export function visible(chapters: Chapter[]): { chapter: Chapter; index: number }[] {
  return chapters.map((chapter, index) => ({ chapter, index })).filter(({ chapter }) => chapter.kind !== "text" || chapter.body.trim() !== "");
}

/** A chapter as the page lists it: where it sits in the text, and its number among the chapters (markers: 0). */
export type Entry = { chapter: Chapter; index: number; n: number };

export type OutlineItem =
  | { kind: "chapter"; entry: Entry }
  | { kind: "marker"; entry: Entry }
  | { kind: "region"; start: Entry; end: Entry; entries: Entry[] };

/** The visible chapters, numbered, with what lies between an `X_START` and its `X_END` marker gathered into a region. */
export function outline(chapters: Chapter[]): OutlineItem[] {
  let n = 0;
  const entries: Entry[] = visible(chapters).map(({ chapter, index }) => ({ chapter, index, n: chapter.kind === "marker" ? 0 : ++n }));
  const items: OutlineItem[] = [];
  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];
    if (entry.chapter.kind !== "marker") {
      items.push({ kind: "chapter", entry });
      continue;
    }
    const base = /^(.+)_START$/.exec(entry.chapter.tag ?? "")?.[1];
    const close = base ? entries.findIndex((e, j) => j > i && e.chapter.kind === "marker" && e.chapter.tag === `${base}_END`) : -1;
    if (close === -1) {
      items.push({ kind: "marker", entry });
      continue;
    }
    items.push({ kind: "region", start: entry, end: entries[close], entries: entries.slice(i + 1, close) });
    i = close;
  }
  return items;
}

import { useEffect, useMemo, useRef } from "react";
import { BookOpen, ChevronLeft, ChevronRight, Download, Loader2, PenLine } from "lucide-react";
import { artBase, type ValeChapter, type ValeGame } from "@/api/vale";
import SceneArt from "./SceneArt";
import { capital, type ValeStrings } from "./strings";

/** One paragraph of a chapter: *italic* and **bold** as the model wrote them. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).filter(Boolean);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : p.startsWith("*") && p.length > 2 ? <em key={i}>{p.slice(1, -1)}</em> : <span key={i}>{p}</span>,
      )}
    </>
  );
}

const BREAK = /^\s*(＊|\*|\*\s*\*\s*\*|⁂|—{3,}|-{3,})\s*$/;
const SERIF = `"Songti SC", "Noto Serif SC", "Source Han Serif SC", Georgia, "Iowan Old Style", serif`;

function Prose({ text, lang }: { text: string; lang: string }) {
  const blocks = useMemo(() => {
    const body = text.replace(/^#.*\n+/, "");
    const joiner = lang === "en" ? " " : "";
    return body.split(/\n\s*\n/).map((b) => b.split("\n").map((l) => l.trim()).filter(Boolean).join(joiner)).filter(Boolean);
  }, [text, lang]);
  let afterBreak = true;
  return (
    <div className={`vale-prose ${lang === "en" ? "en" : "cjk"}`}>
      {blocks.map((b, i) => {
        if (BREAK.test(b)) {
          afterBreak = true;
          return <div key={i} className="text-center text-muted-foreground my-6 tracking-[1em]">⁂</div>;
        }
        const first = afterBreak;
        afterBreak = false;
        return <p key={i} className={first ? "first" : undefined}><Inline text={b} /></p>;
      })}
    </div>
  );
}

export default function NovelReader({
  game, chapters, writing, day, onDay, onWrite, ui,
}: {
  game: ValeGame; chapters: ValeChapter[]; writing: number[]; day: number | null; onDay: (d: number) => void; onWrite: (d: number) => void; ui: ValeStrings;
}) {
  const top = useRef<HTMLDivElement>(null);
  const chapter = chapters.find((c) => c.day === day) ?? chapters[chapters.length - 1] ?? null;
  const index = chapter ? chapters.indexOf(chapter) : -1;
  // Turning to another chapter brings its first page into view; opening the tab does not move the page.
  const shownDay = useRef(chapter?.day);
  useEffect(() => {
    if (shownDay.current !== undefined && shownDay.current !== chapter?.day) top.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    shownDay.current = chapter?.day;
  }, [chapter?.day]);

  const finished = game.status === "finished" ? game.days : game.clock.day - 1;
  const missing = Array.from({ length: Math.max(0, finished) }, (_, i) => i + 1).filter((d) => !chapters.some((c) => c.day === d));

  const scene = chapter?.scenes?.[0];
  const place = scene ? game.places.find((p) => scene.place.includes(p.name) || p.name.includes(scene.place)) : undefined;
  const pov = scene ? game.villagers.find((v) => scene.pov.includes(v.short) || v.name.includes(scene.pov)) : undefined;
  const hour = scene ? Math.max(0, game.waves.findIndex((w) => scene.when.includes(w))) : 4;

  const download = () => {
    const book = `# ${game.story.title || game.name}\n\n` + chapters.map((c) => c.text.trim()).join("\n\n\n");
    const url = URL.createObjectURL(new Blob([book], { type: "text/markdown;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${game.story.title || game.name}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div ref={top} className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        {chapters.map((c) => (
          <button key={c.day} onClick={() => onDay(c.day)}
            className={`rounded-full px-2.5 py-0.5 text-[11.5px] border ${c.day === chapter?.day ? "bg-foreground text-background border-foreground" : "border-border/60 text-muted-foreground hover:bg-muted/40"}`}>
            {ui.chapterNo(c.day)}{c.title ? ` · ${c.title}` : ""}
          </button>
        ))}
        {writing.map((d) => (
          <span key={`w${d}`} className="rounded-full px-2.5 py-0.5 text-[11.5px] border border-dashed border-primary/60 text-primary flex items-center gap-1">
            <Loader2 className="w-3 h-3 animate-spin" />{ui.writingChapter(d)}
          </span>
        ))}
        {chapters.length > 0 && (
          <button onClick={download} className="ml-auto rounded-md border border-border/60 px-2 py-0.5 text-[11.5px] flex items-center gap-1 hover:bg-muted/40">
            <Download className="w-3 h-3" />{ui.download}
          </button>
        )}
      </div>
      {missing.filter((d) => !writing.includes(d)).length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted-foreground">
          {missing.filter((d) => !writing.includes(d)).map((d) => (
            <button key={d} onClick={() => onWrite(d)} className="rounded-md border border-border/60 px-2 py-0.5 flex items-center gap-1 hover:bg-muted/40">
              <PenLine className="w-3 h-3" />{ui.writeChapter(d)}
            </button>
          ))}
        </div>
      )}

      {!chapter ? (
        <div className="rounded-lg border border-dashed border-border/70 p-6 text-center text-sm text-muted-foreground flex flex-col items-center gap-2">
          <BookOpen className="w-5 h-5" />{ui.noChapters}
        </div>
      ) : (
        <article className="rounded-lg border border-border/60 bg-card/40 overflow-hidden">
          <div className="relative aspect-[16/9] sm:aspect-[21/9]">
            <SceneArt className="absolute inset-0 w-full h-full" place={place ? game.art?.places?.[place.id] : { kind: "vale" }}
              s={{ hour, weather: undefined, blight: place ? game.truth.blight[place.id] ?? 0 : 0, shaftOpen: !!game.truth.shaft_open, stoneRaised: !!game.truth.stone_raised }}
              people={pov ? [{ id: pov.id, name: pov.short, color: pov.color, art: game.art?.people?.[pov.id] }] : []}
              label={place?.name} imageBase={artBase(game.story.id)} />
            <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />
            <div className="absolute left-0 right-0 bottom-0 p-2.5 sm:p-4 text-white">
              <div className="text-[12px] opacity-80">{capital(ui.day(chapter.day))}</div>
              <h2 className="text-base sm:text-2xl font-semibold leading-snug" style={{ fontFamily: SERIF }}>{chapter.text.split("\n")[0].replace(/^#\s*/, "")}</h2>
            </div>
          </div>
          <div className="px-3 sm:px-8 py-5 sm:py-6">
            <Prose text={chapter.text} lang={game.lang} />
          </div>
          <div className="flex items-center justify-between border-t border-border/50 px-4 py-2 text-[12px]">
            <button disabled={index <= 0} onClick={() => onDay(chapters[index - 1].day)} className="flex items-center gap-1 disabled:opacity-30 hover:underline">
              <ChevronLeft className="w-3.5 h-3.5" />{ui.prevChapter}
            </button>
            <button disabled={index < 0 || index >= chapters.length - 1} onClick={() => onDay(chapters[index + 1].day)} className="flex items-center gap-1 disabled:opacity-30 hover:underline">
              {ui.nextChapter}<ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </article>
      )}
      <style>{`
        .vale-prose { font-family: ${SERIF}; color: hsl(var(--foreground)); max-width: 40em; margin: 0 auto; }
        .vale-prose p { margin: 0 0 0.9em; line-height: 2; font-size: 16.5px; }
        .vale-prose.cjk p { text-indent: 2em; text-align: justify; }
        .vale-prose.en p { line-height: 1.8; text-indent: 1.4em; margin: 0 0 0.25em; }
        .vale-prose.en p.first { text-indent: 0; }
        .vale-prose em { font-style: italic; color: hsl(var(--muted-foreground)); }
      `}</style>
    </div>
  );
}

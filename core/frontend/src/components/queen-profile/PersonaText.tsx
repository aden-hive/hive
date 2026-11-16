import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AlertCircle, Check, FileText, Loader2, Pencil } from "lucide-react";
import { ApiError } from "@/api/client";
import { isFullMotion } from "@/lib/motion";
import { chapterLabel, isUntitled, joinChapters, outline, parseChapters, readingBody, withBody, type Entry } from "./persona-chapters";

/**
 * Her persona text (profile.yaml `core_traits`), read in the chapters it is written in. A chapter is
 * edited on its own and put back where it was, in the style it was written; the whole text can be
 * edited at once too, to add, move or remove chapters.
 */

export function scrollToId(id: string): void {
  document.getElementById(id)?.scrollIntoView?.({ behavior: isFullMotion() ? "smooth" : "auto", block: "start" });
}

const chapterId = (index: number) => `qp-chapter-${index}`;

/** Text with its `**bold**` set in bold. Nothing else is read as markup: the text is a prompt, not a page. */
function withEmphasis(text: string): ReactNode[] {
  return text.split(/(\*\*[^*\n]+?\*\*)/g).map((part, i) => (/^\*\*[^*\n]+\*\*$/.test(part) ? <strong key={i}>{part.slice(2, -2)}</strong> : part));
}

/** A chapter's text, folded when it runs past a few lines as laid out, with a way to read all of it. */
function Folded({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || open) return;
    const measure = () => setOverflows(el.scrollHeight > el.clientHeight + 2);
    measure();
    // The width changes with the window and the sidebar, and with it how many lines the text takes.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(el);
    return () => observer?.disconnect();
  }, [text, open]);
  return (
    <>
      <div ref={ref} className="qp-chapter-body" data-folded={open ? undefined : ""} data-overflows={overflows && !open ? "" : undefined}>
        {withEmphasis(text)}
      </div>
      {(overflows || open) && (
        <button className="qp-chapter-more" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Fold it" : `Read all · ${text.length.toLocaleString()} characters`}
        </button>
      )}
    </>
  );
}

function TextEditor({
  initial,
  label,
  page,
  onSave,
  onCancel,
}: {
  initial: string;
  label: string;
  page?: boolean;
  onSave: (text: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    try {
      // On success the editor closes; only a failure leaves it open to try again.
      await onSave(draft);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save her persona");
      setSaving(false);
    }
  };

  return (
    <div className="mt-3">
      <textarea
        className="qp-editor"
        data-size={page ? "page" : undefined}
        aria-label={label}
        value={draft}
        autoFocus
        spellCheck={false}
        rows={page ? 24 : Math.min(30, Math.max(5, draft.split("\n").length + 1))}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            void save();
          }
          if (e.key === "Escape") onCancel();
        }}
      />
      <div className="qp-edit-foot">
        <span className="qp-hint">{draft.length.toLocaleString()} characters · Ctrl+Enter saves · Esc cancels</span>
        <div>
          <button className="qp-btn" data-tone="quiet" data-size="sm" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
          <button className="qp-btn" data-tone="primary" data-size="sm" onClick={() => void save()} disabled={saving || draft === initial}>
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            Save
          </button>
        </div>
      </div>
      {error && (
        <p className="qp-error mt-2">
          <AlertCircle className="w-3.5 h-3.5" /> {error}
        </p>
      )}
    </div>
  );
}

export default function PersonaText({ text, onSave }: { text: string; onSave: (text: string) => Promise<void> }) {
  const chapters = useMemo(() => parseChapters(text), [text]);
  const items = useMemo(() => outline(chapters), [chapters]);
  const entries = useMemo(
    () => items.flatMap((item) => (item.kind === "region" ? item.entries : [item.entry])).filter((e) => e.n > 0),
    [items],
  );
  // A chapter's index in the text, or the whole text, being edited.
  const [editing, setEditing] = useState<number | "all" | null>(null);

  const saveChapter = async (index: number, body: string) => {
    const next = chapters.slice();
    next[index] = withBody(chapters[index], body);
    await onSave(joinChapters(next));
    setEditing(null);
  };

  if (editing === "all") {
    return (
      <TextEditor
        page
        initial={text}
        label="Her whole persona text"
        onSave={async (next) => {
          await onSave(next);
          setEditing(null);
        }}
        onCancel={() => setEditing(null)}
      />
    );
  }
  if (!text.trim()) {
    return (
      <div className="qp-empty flex flex-wrap items-center justify-between gap-3">
        <span>She has no persona text yet: nothing tells her who she is.</span>
        <button className="qp-btn" data-size="sm" onClick={() => setEditing("all")}>
          <Pencil className="w-3.5 h-3.5" /> Write it
        </button>
      </div>
    );
  }

  const renderEntry = ({ chapter, index, n }: Entry) => {
    if (chapter.kind === "marker") {
      return (
        <p key={index} className="qp-marker">
          {chapter.tag}
        </p>
      );
    }
    const name = chapterLabel(chapter);
    const body = readingBody(chapter);
    const tag = chapter.kind === "block" && <span className="qp-chapter-tag">&lt;{chapter.tag}&gt;</span>;
    const edit = (
      <button className="qp-icon-btn" onClick={() => setEditing(index)} title="Edit this chapter" aria-label={`Edit “${name}”`}>
        <Pencil className="w-3.5 h-3.5" />
      </button>
    );
    if (editing === index) {
      return (
        <article key={index} id={chapterId(index)} className="qp-card qp-chapter">
          <header className="qp-chapter-head">
            <h3 className="qp-chapter-title">{name}</h3>
            {tag}
          </header>
          <TextEditor initial={chapter.body} label={`“${name}”, as written`} onSave={(next) => saveChapter(index, next)} onCancel={() => setEditing(null)} />
        </article>
      );
    }
    // A line that is only a heading reads as one, not as an empty card.
    if (chapter.kind === "text" && !body) {
      return (
        <div key={index} id={chapterId(index)} className="qp-heading">
          <h3>{name}</h3>
          <span className="qp-chapter-tools">{edit}</span>
        </div>
      );
    }
    // Untitled text between chapters reads as an aside to them.
    if (isUntitled(chapter)) {
      return (
        <div key={index} id={chapterId(index)} className="qp-aside">
          <Folded text={body} />
          <div className="qp-chapter-tools">{edit}</div>
        </div>
      );
    }
    return (
      <article key={index} id={chapterId(index)} className="qp-card qp-chapter" data-n={String(n).padStart(2, "0")}>
        <header className="qp-chapter-head">
          <h3 className="qp-chapter-title">{name}</h3>
          {tag}
        </header>
        <Folded text={body} />
        <div className="qp-chapter-tools">{edit}</div>
      </article>
    );
  };

  return (
    <>
      <div className="qp-toolbar">
        <span className="qp-meta">
          {entries.length} {entries.length === 1 ? "chapter" : "chapters"} · {text.length.toLocaleString()} characters
        </span>
        <button className="qp-btn" data-size="sm" onClick={() => setEditing("all")}>
          <FileText className="w-3.5 h-3.5" /> Edit the whole text
        </button>
      </div>
      {entries.length > 1 && (
        <nav className="qp-contents" aria-label="Chapters">
          {entries.map(({ chapter, index, n }) => (
            <button key={index} onClick={() => scrollToId(chapterId(index))} title={chapterLabel(chapter)}>
              <span className="qp-contents-n">{String(n).padStart(2, "0")}</span>
              {chapterLabel(chapter)}
            </button>
          ))}
        </nav>
      )}
      <div className="qp-chapters">
        {items.map((item) =>
          item.kind === "region" ? (
            <div key={item.start.index} className="flex flex-col gap-[14px]">
              <p className="qp-marker">{item.start.chapter.tag}</p>
              <div className="qp-region">{item.entries.map(renderEntry)}</div>
              <p className="qp-marker">{item.end.chapter.tag}</p>
            </div>
          ) : (
            renderEntry(item.entry)
          ),
        )}
      </div>
    </>
  );
}

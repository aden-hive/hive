import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, Check, ChevronRight, Hexagon, Library, Loader2, Pencil, Plus, Wrench } from "lucide-react";
import { ApiError } from "@/api/client";
import { queensApi, type QueenOverview, type QueenPersona, type QueenSoul } from "@/api/queens";
import { useColony } from "@/context/ColonyContext";
import { useCreateColony } from "@/context/CreateColonyContext";
import { useQueenDecommission } from "@/lib/me";
import { RollingNumber } from "@/components/fx/RollingNumber";
import QueenModelSection from "@/components/QueenModelSection";
import QueenSoulSection from "@/components/QueenSoulSection";
import ProfileHero, { useQueenAvatar, type HeroStat } from "@/components/queen-profile/ProfileHero";
import PersonaText, { scrollToId } from "@/components/queen-profile/PersonaText";
import PersonaPillars from "@/components/queen-profile/PersonaPillars";
import { useAvatarAccent } from "@/components/queen-profile/avatar-accent";
import { splitSkills } from "@/components/queen-profile/skills";

/**
 * A queen's profile: who she is (her persona), what she has become (her soul), the model she
 * thinks with, what she remembers, what she can do and the colonies she leads, read and set on
 * one page.
 */

const SECTIONS = [
  { id: "persona", label: "Persona", title: "Who she is", lede: "The text every chat with her starts from, in the chapters it is written in." },
  { id: "soul", label: "Soul", title: "What she has become", lede: "Her own notes about herself, revised once a day from her chats." },
  { id: "mind", label: "Mind", title: "How she thinks", lede: "The model behind her voice." },
  { id: "memory", label: "Memory", title: "What she remembers", lede: "The notes she keeps across chats." },
  { id: "craft", label: "Craft", title: "What she can do", lede: "What she is good at, in her own profile's words, and the skills and tools she may use." },
  { id: "colonies", label: "Colonies", title: "Where she leads", lede: "The colonies she runs." },
] as const;
type SectionId = (typeof SECTIONS)[number]["id"];
type PersonaFields = Partial<Record<keyof QueenPersona, unknown>>;

const domId = (id: SectionId) => `qp-${id}`;

function shortDate(day: string): string {
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(day);
  return m ? `${Number(m[1])}/${Number(m[2])}` : day;
}

/** A day in the reader's own numeric format, short enough for a cell of the stats plate. */
function calendarDate(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { year: "numeric", month: "numeric", day: "numeric" });
}

function ago(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (Number.isNaN(minutes)) return "—";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return days < 60 ? `${days} d ago` : calendarDate(iso);
}

function label(key: string): string {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The newest line of the first part of her soul that says anything: the hero quotes it. */
function epigraphOf(soul: QueenSoul | null): { text: string; by: string } | null {
  if (!soul?.enabled) return null;
  const section = soul.sections.find((s) => s.items.length > 0);
  if (!section) return null;
  const newest = [...section.items].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0)).at(-1)!;
  return { text: newest.text, by: ["Her soul", section.title, newest.date && shortDate(newest.date)].filter(Boolean).join(" · ") };
}

function Section({ id, actions, children }: { id: SectionId; actions?: ReactNode; children: ReactNode }) {
  const index = SECTIONS.findIndex((s) => s.id === id);
  const { label: kicker, title, lede } = SECTIONS[index];
  return (
    <section id={domId(id)} className="qp-section" aria-labelledby={`${domId(id)}-title`}>
      <p className="qp-kicker">
        <span className="qp-kicker-num">{String(index + 1).padStart(2, "0")}</span>
        {kicker}
        <span className="fx-ruler" aria-hidden />
      </p>
      <div className="qp-section-head">
        <div className="min-w-0">
          <h2 id={`${domId(id)}-title`} className="qp-section-title">
            {title}
          </h2>
          <p className="qp-section-lede">{lede}</p>
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

function MemoryPanel({ overview, onOpen }: { overview: QueenOverview | null; onOpen: () => void }) {
  if (!overview) {
    return (
      <div className="qp-card qp-memory">
        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
      </div>
    );
  }
  const { count, limit, by_type } = overview.memory;
  const kinds = Object.entries(by_type).sort((a, b) => b[1] - a[1]);
  // One colour, in steps: the kinds are parts of one memory, not rival series.
  const shade = (i: number) => [1, 0.68, 0.46, 0.3][i] ?? 0.18;
  return (
    <div className="qp-card qp-memory">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <p>
          <span className="qp-memory-count">
            <RollingNumber value={count} />
          </span>
          <span className="qp-memory-of">of {limit} notes</span>
        </p>
        <button className="qp-btn" data-size="sm" onClick={onOpen}>
          <Library className="w-3.5 h-3.5" /> Open her memories
        </button>
      </div>
      <div className="qp-membar" aria-hidden>
        {kinds.map(([kind, n], i) => (
          <span key={kind} style={{ flex: n, "--o": shade(i) } as CSSProperties} />
        ))}
        {limit > count && <span data-room style={{ flex: limit - count }} />}
      </div>
      {kinds.length > 0 && (
        <div className="qp-legend">
          {kinds.map(([kind, n], i) => (
            <span key={kind}>
              <i style={{ "--o": shade(i) } as CSSProperties} />
              {label(kind)} <b>{n}</b>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function SkillsField({ skills, onSave }: { skills: string; onSave: (skills: string) => Promise<void> }) {
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const items = splitSkills(skills);

  if (draft !== null) {
    const save = async () => {
      setSaving(true);
      try {
        await onSave(draft.trim());
        setDraft(null);
        setError(null);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Couldn't save her skills");
      } finally {
        setSaving(false);
      }
    };
    return (
      <div className="mt-[22px]">
        <textarea
          className="qp-editor"
          aria-label="Her skills"
          value={draft}
          autoFocus
          rows={Math.max(3, Math.ceil(draft.length / 90))}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void save();
            if (e.key === "Escape") setDraft(null);
          }}
        />
        <div className="qp-edit-foot">
          <span className="qp-hint">Separate skills with commas · Ctrl+Enter saves</span>
          <div>
            <button className="qp-btn" data-tone="quiet" data-size="sm" onClick={() => setDraft(null)} disabled={saving}>
              Cancel
            </button>
            <button className="qp-btn" data-tone="primary" data-size="sm" onClick={() => void save()} disabled={saving}>
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
  return (
    <div className="qp-skills">
      {items.map((skill) => (
        <span key={skill} className="qp-skill">
          {skill}
        </span>
      ))}
      <button className="qp-add" onClick={() => setDraft(skills)}>
        {items.length ? <Pencil className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
        {items.length ? "Edit" : "Say what she is good at"}
      </button>
    </div>
  );
}

export default function QueenProfilePage() {
  const { queenId = "" } = useParams<{ queenId: string }>();
  // Keyed on the queen: moving to another queen starts afresh, never one queen's state under another's name.
  return <QueenProfile key={queenId} queenId={queenId} />;
}

function QueenProfile({ queenId }: { queenId: string }) {
  const navigate = useNavigate();
  const location = useLocation();
  // Back to wherever she was opened from (org chart, her chat, a chat bubble); a page opened
  // directly, with nothing of the app behind it, goes back to the org chart instead.
  const back = () => (location.key === "default" ? navigate("/org-chart") : navigate(-1));
  const { queenProfiles, colonies, refresh } = useColony();
  const { openCreateColony } = useCreateColony();
  const { isDecommissioned, setDecommissioned, saving: retiring } = useQueenDecommission(queenId);
  const summary = queenProfiles.find((q) => q.id === queenId);
  const avatar = useQueenAvatar(queenId);
  const { accent, ready } = useAvatarAccent(avatar.url);

  const [persona, setPersona] = useState<QueenPersona | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [overview, setOverview] = useState<QueenOverview | null>(null);
  const [soul, setSoul] = useState<QueenSoul | null>(null);
  const [model, setModel] = useState("");

  useEffect(() => {
    queensApi
      .getPersona(queenId)
      .then((r) => setPersona(r.persona))
      .catch((e) =>
        setFailure(e instanceof ApiError && e.status === 404 ? "There is no queen by this id." : e instanceof ApiError ? e.message : "Couldn't load her profile"),
      );
    queensApi
      .getOverview(queenId)
      .then(setOverview)
      .catch(() => {});
  }, [queenId]);

  const savePersona = useCallback(
    async (fields: PersonaFields) => {
      const res = await queensApi.setPersona(queenId, fields);
      setPersona(res.persona);
      // The sidebar, header and org chart show her name and title too.
      if ("name" in fields || "title" in fields) refresh();
    },
    [queenId, refresh],
  );

  // The section being read: the last one whose top has passed a line a third of the way down.
  const scroller = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<SectionId>("persona");
  const loaded = persona !== null;
  useEffect(() => {
    const root = scroller.current;
    if (!root || !loaded) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const line = root.getBoundingClientRect().top + root.clientHeight * 0.3;
      let current: SectionId = SECTIONS[0].id;
      for (const s of SECTIONS) {
        const top = document.getElementById(domId(s.id))?.getBoundingClientRect().top;
        if (top !== undefined && top <= line) current = s.id;
      }
      // The last sections are too short to reach the line; at the bottom, the last one is read.
      if (root.scrollTop > 0 && root.scrollTop + root.clientHeight >= root.scrollHeight - 2) current = SECTIONS[SECTIONS.length - 1].id;
      setActive(current);
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    root.addEventListener("scroll", onScroll, { passive: true });
    update();
    return () => {
      root.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(frame);
    };
  }, [loaded]);

  if (failure) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 p-8 text-center">
        <p className="qp-error text-sm">
          <AlertCircle className="w-4 h-4" /> {failure}
        </p>
        <button className="qp-btn" data-size="sm" onClick={() => navigate("/org-chart")}>
          See all queens
        </button>
      </div>
    );
  }

  const name = persona?.name ?? summary?.name ?? queenId;
  const title = persona?.title ?? summary?.title ?? "";
  const pending = soul?.enabled && soul.proposal ? soul.proposal.edits.length : 0;
  const led = colonies.filter((c) => c.queenProfileId === queenId);

  const stats: HeroStat[] = [];
  if (overview) {
    stats.push({ label: "Memories", value: <RollingNumber value={overview.memory.count} /> });
    stats.push({ label: "Chats", value: <RollingNumber value={overview.sessions.count} /> });
    if (overview.sessions.first) stats.push({ label: "With you since", value: calendarDate(overview.sessions.first) });
    if (overview.sessions.last_active) stats.push({ label: "Last active", value: ago(overview.sessions.last_active), title: overview.sessions.last_active });
  }
  if (soul?.enabled) stats.push({ label: "Soul", value: soul.version ? `v${soul.version}` : "—", note: pending ? `${pending} waiting` : undefined });
  // The model's own name reads better than its provider path; the whole id is in the tooltip.
  if (model) stats.push({ label: "Model", value: model.split("/").pop(), mono: true, title: model });

  return (
    <div
      ref={scroller}
      className="qp flex-1 min-h-0 overflow-y-auto"
      data-aura={ready ? undefined : "pending"}
      data-retired={isDecommissioned ? "" : undefined}
      style={accent ? ({ "--qp-accent": accent } as CSSProperties) : undefined}
    >
      <ProfileHero
        queenId={queenId}
        name={name}
        title={title}
        portrait={summary?.portrait}
        avatar={avatar}
        epigraph={epigraphOf(soul)}
        stats={stats}
        retired={isDecommissioned}
        retiring={retiring}
        onSaveIdentity={(nextName, nextTitle) => savePersona({ name: nextName, title: nextTitle })}
        onEpigraph={() => scrollToId(domId("soul"))}
        onMessage={() => navigate(`/queen/${queenId}`)}
        onNewColony={() => openCreateColony({ queenId })}
        onRetire={(retired) => void setDecommissioned(retired)}
        onBack={back}
      />

      <div className="qp-body">
        <nav className="qp-toc" aria-label="Sections">
          <p className="qp-toc-label">Contents</p>
          <div className="qp-toc-list">
            {SECTIONS.map((s, i) => (
              <button key={s.id} className="qp-toc-item" aria-current={active === s.id ? "location" : undefined} onClick={() => scrollToId(domId(s.id))}>
                <span className="qp-toc-num">{String(i + 1).padStart(2, "0")}</span>
                {s.label}
                {s.id === "soul" && pending > 0 && (
                  <span className="qp-toc-badge" title={`${pending} changes wait for you`}>
                    {pending}
                  </span>
                )}
              </button>
            ))}
          </div>
        </nav>

        <div className="qp-main">
          {persona === null ? (
            <div className="qp-section">
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <>
              <Section id="persona">
                <PersonaText text={persona.core_traits ?? ""} onSave={(text) => savePersona({ core_traits: text })} />
                <p className="qp-sub">
                  Beneath the surface
                  <span className="fx-ruler" aria-hidden />
                </p>
                <PersonaPillars persona={persona} onSave={savePersona} />
              </Section>

              <Section id="soul">
                <QueenSoulSection queenId={queenId} onChange={setSoul} />
              </Section>

              <Section id="mind">
                <div className="mt-[22px]">
                  <QueenModelSection queenId={queenId} onChange={setModel} />
                </div>
              </Section>

              <Section id="memory">
                <MemoryPanel overview={overview} onOpen={() => navigate(`/memory-library?queen=${queenId}`)} />
              </Section>

              <Section id="craft">
                <SkillsField skills={persona.skills ?? ""} onSave={(skills) => savePersona({ skills })} />
                <div className="qp-links">
                  <button className="qp-card qp-link" onClick={() => navigate(`/skills-library?queen=${queenId}`)}>
                    <span className="qp-pillar-icon">
                      <Library className="w-4 h-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="qp-link-title block">Skills</span>
                      <span className="qp-link-note block">The skills she may load, from the library</span>
                    </span>
                    <ChevronRight className="w-4 h-4 text-muted-foreground" />
                  </button>
                  <button className="qp-card qp-link" onClick={() => navigate(`/skills-library?tab=mcp&queen=${queenId}`)}>
                    <span className="qp-pillar-icon">
                      <Wrench className="w-4 h-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="qp-link-title block">Tools</span>
                      <span className="qp-link-note block">The tools she may use</span>
                    </span>
                    <ChevronRight className="w-4 h-4 text-muted-foreground" />
                  </button>
                </div>
              </Section>

              <Section id="colonies">
                <div className="qp-colonies">
                  {led.map((colony) => (
                    <button key={colony.id} className="qp-card qp-colony" onClick={() => navigate(`/colony/${colony.id}`)}>
                      <span className="qp-colony-name">
                        <Hexagon className="w-4 h-4 text-primary" />
                        {colony.name}
                      </span>
                      <span className="qp-colony-status" data-state={colony.status}>
                        {colony.status}
                        {colony.lastActive ? ` · ${ago(colony.lastActive)}` : ""}
                      </span>
                      {colony.task && <span className="qp-colony-task">{colony.task}</span>}
                    </button>
                  ))}
                  {!isDecommissioned && (
                    <button className="qp-card qp-colony" data-new onClick={() => openCreateColony({ queenId })}>
                      <Plus className="w-4 h-4" />
                      New colony
                    </button>
                  )}
                </div>
              </Section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

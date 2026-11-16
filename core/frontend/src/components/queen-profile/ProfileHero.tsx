import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { AlertCircle, ArrowLeft, Camera, Check, Loader2, MessageSquare, Pencil, Plus, Trash2, UserMinus, UserPlus } from "lucide-react";
import { apiUrl, ApiError } from "@/api/client";
import { queensApi, type PortraitDescriptor } from "@/api/queens";
import { useColony } from "@/context/ColonyContext";
import { compressImage } from "@/lib/image-utils";
import { ScrambleText } from "@/components/fx/ScrambleText";
import QueenPortraitGlyph from "@/components/QueenPortraitGlyph";
import HoneycombAura from "./HoneycombAura";

/**
 * The top of a queen's profile: her portrait in a honeycomb cell, her name and title (editable in
 * place), a line from her soul, what you can do with her, and her numbers.
 */

export type HeroStat = { label: string; value: ReactNode; note?: string; mono?: boolean; title?: string };

/** Her uploaded picture, if any, and how to change it. */
export function useQueenAvatar(queenId: string) {
  const { queenAvatarVersion, queenHasAvatar, bumpQueenAvatar } = useColony();
  const version = queenAvatarVersion(queenId);
  const listed = queenHasAvatar(queenId);
  const [present, setPresent] = useState(listed);
  // The listing can confirm a picture after the page opened.
  useEffect(() => {
    if (listed) setPresent(true);
  }, [listed]);
  const [busy, setBusy] = useState<"upload" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (kind: "upload" | "delete", action: () => Promise<boolean>) => {
    setBusy(kind);
    setError(null);
    try {
      setPresent(await action());
      // Every other picture of her (sidebar, chats, org chart) loads again.
      bumpQueenAvatar(queenId);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : kind === "upload" ? "Couldn't upload the picture" : "Couldn't remove the picture");
    } finally {
      setBusy(null);
    }
  };

  return {
    url: present ? apiUrl(`/queen/${queenId}/avatar?v=${version}`) : null,
    busy,
    error,
    upload: (file: File) => {
      if (!file.type.startsWith("image/")) return;
      void run("upload", async () => {
        await queensApi.uploadAvatar(queenId, await compressImage(file));
        return true;
      });
    },
    remove: () =>
      void run("delete", async () => {
        await queensApi.deleteAvatar(queenId);
        return false;
      }),
    /** The listed picture is gone (deleted elsewhere). */
    missing: () => setPresent(false),
  };
}

type Props = {
  queenId: string;
  name: string;
  title: string;
  portrait?: PortraitDescriptor | null;
  avatar: ReturnType<typeof useQueenAvatar>;
  epigraph: { text: string; by: string } | null;
  stats: HeroStat[];
  retired: boolean;
  retiring: boolean;
  onSaveIdentity: (name: string, title: string) => Promise<void>;
  onEpigraph: () => void;
  onMessage: () => void;
  onNewColony: () => void;
  onRetire: (retired: boolean) => void;
  onBack: () => void;
};

/** The ring round the portrait: a pointy-top hexagon a little larger than it. */
const RING = [
  [0, -132],
  [114.3, -66],
  [114.3, 66],
  [0, 132],
  [-114.3, 66],
  [-114.3, -66],
];

export default function ProfileHero({
  queenId,
  name,
  title,
  portrait,
  avatar,
  epigraph,
  stats,
  retired,
  retiring,
  onSaveIdentity,
  onEpigraph,
  onMessage,
  onNewColony,
  onRetire,
  onBack,
}: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState<{ name: string; title: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      await onSaveIdentity(draft.name.trim(), draft.title.trim());
      setDraft(null);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save her name");
    } finally {
      setSaving(false);
    }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") void save();
    if (e.key === "Escape") setDraft(null);
  };

  return (
    <header className="qp-hero">
      <div className="qp-hero-bar">
        <button className="qp-back" onClick={onBack}>
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>
      </div>
      <div className="qp-hero-inner">
        <div className="qp-portrait-slot qp-reveal" style={{ "--i": 0 } as CSSProperties}>
          <div className="qp-aura">
            <HoneycombAura seed={queenId} />
          </div>
          <div className="qp-portrait">
            <div className="qp-portrait-edge" />
            <div className="qp-portrait-face">
              {avatar.url ? (
                <img src={avatar.url} alt={name} onError={avatar.missing} />
              ) : portrait ? (
                <QueenPortraitGlyph p={portrait} frame={false} />
              ) : (
                <span className="qp-portrait-initial">{name.charAt(0)}</span>
              )}
              <div className="qp-portrait-tools">
                <button onClick={() => fileRef.current?.click()} disabled={avatar.busy !== null} title="Change her picture" aria-label="Change her picture">
                  {avatar.busy === "upload" ? <Loader2 className="w-5 h-5 animate-spin" /> : <Camera className="w-5 h-5" />}
                </button>
                {avatar.url && (
                  <button onClick={avatar.remove} disabled={avatar.busy !== null} data-danger title="Remove her picture" aria-label="Remove her picture">
                    {avatar.busy === "delete" ? <Loader2 className="w-5 h-5 animate-spin" /> : <Trash2 className="w-5 h-5" />}
                  </button>
                )}
              </div>
            </div>
          </div>
          <svg className="qp-portrait-ring" viewBox="-134 -134 268 268" aria-hidden>
            <polygon points={RING.map((p) => p.join(",")).join(" ")} pathLength={1} />
            {RING.map(([x, y]) => (
              <circle key={`${x},${y}`} cx={x} cy={y} r={2.2} />
            ))}
          </svg>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              // Clear it so choosing the same file again still fires.
              e.target.value = "";
              if (file) avatar.upload(file);
            }}
          />
        </div>

        <div className="qp-identity">
          <p className="qp-eyebrow qp-reveal" style={{ "--i": 1 } as CSSProperties}>
            <ScrambleText text="Queen dossier" />
            <span className="qp-eyebrow-id">// {queenId}</span>
            <span className="fx-ruler" aria-hidden />
          </p>

          {draft ? (
            <div>
              <input
                aria-label="Her name"
                className="qp-name-input"
                value={draft.name}
                autoFocus
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                onKeyDown={onKey}
              />
              <input
                aria-label="Her title"
                className="qp-title-input"
                value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                onKeyDown={onKey}
              />
              <div className="qp-actions">
                <button className="qp-btn" data-tone="primary" data-size="sm" onClick={() => void save()} disabled={saving || !draft.name.trim() || !draft.title.trim()}>
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                  Save
                </button>
                <button className="qp-btn" data-tone="quiet" data-size="sm" onClick={() => setDraft(null)} disabled={saving}>
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="qp-name-row">
                <h1 className="qp-name">{name}</h1>
                <button className="qp-icon-btn" onClick={() => setDraft({ name, title })} title="Edit her name and title" aria-label="Edit her name and title">
                  <Pencil className="w-3.5 h-3.5" />
                </button>
              </div>
              {title && (
                <p className="qp-title qp-reveal" style={{ "--i": 2 } as CSSProperties}>
                  {title}
                </p>
              )}
            </>
          )}
          {(error || avatar.error) && (
            <p className="qp-error mt-3">
              <AlertCircle className="w-3.5 h-3.5" /> {error ?? avatar.error}
            </p>
          )}

          {epigraph && !draft && (
            <button className="qp-epigraph qp-reveal" style={{ "--i": 3 } as CSSProperties} onClick={onEpigraph} title="Read her soul">
              <span className="qp-epigraph-text">“{epigraph.text}”</span>
              <span className="qp-epigraph-by block">— {epigraph.by}</span>
            </button>
          )}

          {retired ? (
            <div className="qp-retired qp-reveal" style={{ "--i": 4 } as CSSProperties}>
              <span>Decommissioned: hidden from your sidebar, colonies and pickers.</span>
              <button className="qp-btn" data-size="sm" onClick={() => onRetire(false)} disabled={retiring}>
                {retiring ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <UserPlus className="w-3.5 h-3.5" />}
                Hire back
              </button>
            </div>
          ) : (
            !draft && (
              <div className="qp-actions qp-reveal" style={{ "--i": 4 } as CSSProperties}>
                <button className="qp-btn" data-tone="primary" onClick={onMessage}>
                  <MessageSquare className="w-4 h-4" />
                  Message
                </button>
                <button className="qp-btn" onClick={onNewColony}>
                  <Plus className="w-4 h-4" />
                  New colony
                </button>
                <button className="qp-btn" data-tone="danger" onClick={() => onRetire(true)} disabled={retiring}>
                  {retiring ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserMinus className="w-4 h-4" />}
                  Decommission
                </button>
              </div>
            )
          )}
        </div>
      </div>

      {stats.length > 0 && (
        <div className="qp-hero-foot qp-reveal" style={{ "--i": 5 } as CSSProperties}>
          <dl className="qp-stats">
            {stats.map((stat) => (
              <div key={stat.label} className="qp-stat">
                <dt>{stat.label}</dt>
                <dd data-mono={stat.mono ? "" : undefined} title={stat.title}>
                  {stat.value}
                  {stat.note && <span className="qp-stat-note">{stat.note}</span>}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </header>
  );
}

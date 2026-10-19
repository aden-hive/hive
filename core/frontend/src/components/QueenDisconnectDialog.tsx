import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ExternalLink,
  KeyRound,
  Loader2,
  Trash2,
  X,
} from "lucide-react";
import { queensApi, type QueenToolsResponse } from "@/api/queens";
import { ProviderLogo } from "@/components/ProviderLogo";
import { getProviderLogo } from "@/data/providerLogos";

interface QueenRow {
  id: string;
  snapshot: QueenToolsResponse | null;
  /** Names of tools mapped to the provider being removed. */
  providerToolNames: string[];
  /** True iff this queen currently has at least one tool tied to the
   * provider — the others need no rewrite. */
  affected: boolean;
}

/** Provider chip icon. Intentionally a small copy of the same helper in
 * QueensAuthorizationDialog — keeps both dialogs free of cross-imports. */
function ProviderIcon({ provider, size = 18 }: { provider: string; size?: number }) {
  const logo = getProviderLogo(provider);
  if (!logo) return <KeyRound width={size} height={size} />;
  return <ProviderLogo provider={provider} size={size} />;
}

/** Strip the provider's tool names from a queen's allowlist. Same shape
 * as the connect dialog's ``untickQueen``: build an explicit sidecar
 * (so we don't accidentally regress queens that were on allow-all) and
 * intersect with the catalog's known tool names so any stale entries
 * don't trip the PATCH validator. */
async function stripProviderFromQueen(row: QueenRow): Promise<void> {
  if (!row.snapshot) throw new Error("queen tools not loaded");
  const providerSet = new Set(row.providerToolNames);
  const knownNames = new Set(
    row.snapshot.mcp_servers.flatMap((s) => s.tools.map((t) => t.name)),
  );
  const baseList: string[] = Array.isArray(row.snapshot.enabled_mcp_tools)
    ? [...row.snapshot.enabled_mcp_tools]
    : row.snapshot.mcp_servers.flatMap((s) => s.tools.map((t) => t.name));
  const next = Array.from(
    new Set(baseList.filter((n) => !providerSet.has(n) && knownNames.has(n))),
  ).sort();
  await queensApi.updateTools(row.id, next);
}

interface Props {
  open: boolean;
  provider: string;
  accountEmail: string | null;
  /** Invoked after queen sidecars have been rewritten. Used by the
   * credentials page to delete the credential once the user has
   * confirmed. Undefined for SSE-triggered opens (credential is
   * already gone). */
  onConfirm?: () => Promise<void>;
  onClose: () => void;
}

/**
 * Confirms removing an integration, and rewrites every affected queen's
 * tool list to drop that provider's tools.
 *
 * Deliberately not a picker. Removing an integration means removing it —
 * asking the user to review a checklist of nine queens to accept the only
 * outcome they asked for is a decision they never wanted to make. So this
 * states the blast radius and gets out of the way; the tools come back on
 * their own if the account is reconnected later.
 */
export default function QueenDisconnectDialog({
  open,
  provider,
  accountEmail,
  onConfirm,
  onClose,
}: Props) {
  const [rows, setRows] = useState<QueenRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !provider) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setRows([]);
    setConfirmError(null);
    (async () => {
      try {
        const list = await queensApi.list();
        const summaries = list.queens;
        const snapshots = await Promise.all(
          summaries.map(async (q) => {
            try {
              return await queensApi.getTools(q.id);
            } catch {
              return null;
            }
          }),
        );
        if (cancelled) return;
        const built: QueenRow[] = summaries.map((q, i) => {
          const snap = snapshots[i];
          const providerToolNames = snap
            ? Array.from(
                new Set(
                  snap.mcp_servers
                    .flatMap((s) => s.tools)
                    .filter((t) => t.provider === provider)
                    .map((t) => t.name),
                ),
              )
            : [];
          return {
            id: q.id,
            snapshot: snap,
            providerToolNames,
            affected: providerToolNames.length > 0,
          };
        });
        setRows(built);
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, provider]);

  const affected = useMemo(() => rows.filter((r) => r.affected), [rows]);
  const providerLabel = useMemo(() => {
    const logo = getProviderLogo(provider);
    return logo?.name || provider.charAt(0).toUpperCase() + provider.slice(1);
  }, [provider]);

  const handleApply = useCallback(async () => {
    if (applying) return;
    setApplying(true);
    setConfirmError(null);

    const results = await Promise.all(
      affected.map(async (r) => {
        try {
          await stripProviderFromQueen(r);
          return true;
        } catch {
          return false;
        }
      }),
    );
    const failures = results.filter((ok) => !ok).length;
    if (failures > 0) {
      // Leave the credential alive: a half-stripped set of queens plus a
      // deleted account is the one state we can't recover from here.
      setConfirmError(
        `Couldn't update ${failures} of ${affected.length} queens. Nothing was removed — try again.`,
      );
      setApplying(false);
      return;
    }

    // Queens are now stripped — delete the credential (if we own that
    // step). A failure here leaves the queen sidecars updated but the
    // credential alive; surface the error so the user can retry.
    if (onConfirm) {
      try {
        await onConfirm();
      } catch (err) {
        setConfirmError(err instanceof Error ? err.message : String(err));
        setApplying(false);
        return;
      }
    }
    setApplying(false);
    onClose();
  }, [applying, affected, onConfirm, onClose]);

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
        onClick={applying ? undefined : onClose}
      />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md pointer-events-auto flex flex-col">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border/60">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-destructive/10 border border-destructive/20 flex items-center justify-center">
                <ProviderIcon provider={provider} size={18} />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-foreground">
                  {onConfirm
                    ? `Disconnect ${providerLabel}?`
                    : `${providerLabel} disconnected`}
                </h2>
                <p className="text-[11px] text-muted-foreground">
                  {accountEmail
                    ? onConfirm
                      ? `Removing access for ${accountEmail}`
                      : `Access for ${accountEmail} was removed`
                    : "Removing access"}
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              disabled={applying}
              className="p-1.5 rounded-md hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="px-5 pt-4 pb-3">
            {loading && (
              <div className="py-6 flex items-center justify-center">
                <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
              </div>
            )}

            {!loading && loadError && (
              <div className="px-3 py-2 rounded-lg border border-destructive/20 bg-destructive/5 text-xs text-destructive flex items-center gap-2">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                <span className="break-words">Failed to load queens: {loadError}</span>
              </div>
            )}

            {!loading && !loadError && (
              <>
                <p className="text-[11px] text-muted-foreground">
                  {onConfirm ? (
                    <>
                      {providerLabel} tools will be removed from every queen
                      that uses them, then we'll send you to Aden where the
                      account is actually removed.
                    </>
                  ) : (
                    <>
                      {providerLabel} tools will be removed from every queen
                      that still lists them — the account is already gone.
                    </>
                  )}{" "}
                  They come back automatically if you reconnect later.
                </p>

                {affected.length > 0 && (
                  <div className="mt-3 flex items-center gap-3 px-3 py-2.5 rounded-lg border border-destructive/30 bg-destructive/[0.04]">
                    <div className="w-7 h-7 rounded-full bg-destructive/10 flex items-center justify-center flex-shrink-0">
                      <Trash2 className="w-3.5 h-3.5 text-destructive" />
                    </div>
                    <div className="text-xs text-foreground">
                      <span className="font-medium">
                        {affected.length} queen{affected.length === 1 ? "" : "s"}
                      </span>{" "}
                      will lose {providerLabel} tools
                    </div>
                  </div>
                )}

                {affected.length === 0 && (
                  <div className="mt-3 text-xs text-muted-foreground">
                    No queens currently have {providerLabel} tools — safe to
                    remove.
                  </div>
                )}
              </>
            )}
          </div>

          {/* Footer */}
          <div className="flex flex-col gap-2 px-5 py-3 border-t border-border/60">
            {confirmError && (
              <div className="text-[11px] text-destructive flex items-center gap-1.5">
                <AlertCircle className="w-3 h-3 flex-shrink-0" />
                <span className="break-words">{confirmError}</span>
              </div>
            )}
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={onClose}
                disabled={applying}
                className="px-3 py-1.5 rounded-md text-xs font-medium border border-border/60 text-muted-foreground hover:bg-muted/40 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Cancel
              </button>
              <button
                onClick={handleApply}
                disabled={applying || loading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {applying ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : onConfirm ? (
                  <ExternalLink className="w-3 h-3" />
                ) : (
                  <Trash2 className="w-3 h-3" />
                )}
                {onConfirm ? "Continue to Aden" : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

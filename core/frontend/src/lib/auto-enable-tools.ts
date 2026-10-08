import { queensApi } from "@/api/queens";
import { isVisibleTool } from "@/lib/visible-tools";

/** After a successful OAuth connect, walk every queen and add the
 * provider's tools to its allowlist so the user doesn't have to open
 * each queen and tick the boxes manually. Skips queens already on
 * allow-all (``enabled_mcp_tools === null``) and silently ignores
 * per-queen failures so one bad queen doesn't block the rest.
 *
 * Idempotent: re-running for an already-enabled provider is a no-op
 * because each queen's ``getTools`` reflects the current allowlist. */
export async function autoEnableProviderAcrossQueens(
  provider: string,
): Promise<void> {
  let queens: Array<{ id: string }> = [];
  try {
    const list = await queensApi.list();
    queens = list.queens;
  } catch (err) {
    console.warn("[auto-enable] queens.list failed:", err);
    return;
  }
  await Promise.all(
    queens.map(async (q) => {
      try {
        const snapshot = await queensApi.getTools(q.id);
        if (snapshot.enabled_mcp_tools === null) return; // allow-all already
        const newToolNames = snapshot.mcp_servers
          .flatMap((s) => s.tools)
          .filter(
            (t) =>
              t.provider === provider &&
              !t.enabled &&
              isVisibleTool(t.provider, t.name),
          )
          .map((t) => t.name);
        if (newToolNames.length === 0) return;
        const merged = Array.from(
          new Set([...snapshot.enabled_mcp_tools, ...newToolNames]),
        ).sort();
        await queensApi.updateTools(q.id, merged);
      } catch (err) {
        console.warn(`[auto-enable] queen ${q.id} failed:`, err);
      }
    }),
  );
}

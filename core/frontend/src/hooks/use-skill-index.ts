import { useEffect, useState } from "react";
import { skillsApi } from "@/api/skills";
import {
  deriveDomain,
  formatSkillLabel,
  inferSkillCapsules,
  type SkillCapsule,
} from "@/data/skill-capsules";

// The skill library is the same for every composer on screen, so fetch it once
// and share the result process-wide. The cache survives unmounts (the user
// hops between New Chat, a queen DM, and a colony repeatedly); a single
// in-flight promise dedupes concurrent first-mounts.
let cache: SkillCapsule[] | null = null;
let inflight: Promise<SkillCapsule[]> | null = null;

function loadCapsules(): Promise<SkillCapsule[]> {
  if (cache) return Promise.resolve(cache);
  if (!inflight) {
    inflight = skillsApi
      .listAll()
      .then((res) => {
        const seen = new Set<string>();
        const out: SkillCapsule[] = [];
        for (const s of res.skills) {
          if (seen.has(s.name)) continue;
          seen.add(s.name);
          out.push({
            name: s.name,
            label: formatSkillLabel(s.name),
            description: s.description,
            domain: deriveDomain(`${s.name} ${s.description ?? ""}`),
          });
        }
        out.sort((a, b) => a.label.localeCompare(b.label));
        cache = out;
        return out;
      })
      .catch(() => {
        cache = [];
        return [];
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** "hive.linkedin-automation" → "linkedin-automation" for cross-source compare. */
function normalizeSkillName(name: string): string {
  return name.replace(/^hive\./i, "").trim().toLowerCase();
}

/**
 * Does a catalog-inferred capsule correspond to a skill that actually exists in
 * the live library? Names come from two different sources (the static inference
 * catalog uses bare slugs; the live index uses library names), so match on the
 * normalized slug (exact / suffix / prefix) or an exact label.
 */
function liveHasSkill(capsule: SkillCapsule, live: SkillCapsule[]): boolean {
  const slug = normalizeSkillName(capsule.name);
  const label = capsule.label.toLowerCase();
  return live.some((c) => {
    const n = normalizeSkillName(c.name);
    return (
      n === slug ||
      n.endsWith(slug) ||
      n.startsWith(slug) ||
      c.label.toLowerCase() === label
    );
  });
}

/**
 * Infer indicative skill capsules from prompt text, keeping only those that
 * exist in the given live skill index. Pure — callable from event handlers as
 * well as render. Returns [] when the index hasn't loaded yet.
 */
export function inferLiveSkillCapsules(
  text: string,
  live: SkillCapsule[],
  max = 3,
): SkillCapsule[] {
  if (live.length === 0) return [];
  return inferSkillCapsules(text, 20)
    .filter((c) => liveHasSkill(c, live))
    .slice(0, max);
}

/** Live, de-duplicated index of every skill in the library, as capsules. */
export function useSkillIndex(): { capsules: SkillCapsule[]; loading: boolean } {
  const [capsules, setCapsules] = useState<SkillCapsule[]>(cache ?? []);
  const [loading, setLoading] = useState<boolean>(cache === null);

  useEffect(() => {
    if (cache) {
      setCapsules(cache);
      setLoading(false);
      return;
    }
    let cancelled = false;
    void loadCapsules().then((out) => {
      if (cancelled) return;
      setCapsules(out);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return { capsules, loading };
}

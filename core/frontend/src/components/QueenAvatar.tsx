import { useEffect, useState } from "react";
import { apiUrl } from "@/api/client";
import type { QueenProfileSummary } from "@/types/colony";
import { useColony } from "@/context/ColonyContext";
import QueenPortraitGlyph from "./QueenPortraitGlyph";

interface QueenAvatarProps {
  queen: QueenProfileSummary;
  /** Sizing + extra classes for the circle, e.g. "w-6 h-6" (sidebar) or
   *  "w-11 h-11" (setup prompt). The root is the positioned box callers wrap. */
  className?: string;
}

/**
 * A queen's avatar — the canonical chain shared everywhere (sidebar, setup
 * prompt, etc.): uploaded avatar <img> → portrait glyph → name initial.
 *
 * Avatar *presence* is read from ColonyContext (queenHasAvatar) so every
 * consumer stays in sync and first-time users (no avatar uploaded) skip the
 * <img> entirely and never log a 404. A local onError flips us off if a stale
 * listing claimed a file that's since been removed. Extracted from
 * SidebarQueenItem so the setup prompt shows the exact same avatar the user
 * sees in the sidebar — same queen, same picture, guaranteed.
 */
export default function QueenAvatar({ queen, className }: QueenAvatarProps) {
  const { queenAvatarVersion, queenHasAvatar } = useColony();
  const version = queenAvatarVersion(queen.id);
  const [hasAvatar, setHasAvatar] = useState(() => queenHasAvatar(queen.id));
  useEffect(() => setHasAvatar(queenHasAvatar(queen.id)), [version, queen.id, queenHasAvatar]);
  const avatarUrl = apiUrl(`/queen/${queen.id}/avatar?v=${version}`);

  return (
    <span
      className={`flex items-center justify-center rounded-full overflow-hidden bg-primary/15 ${className ?? ""}`}
    >
      {hasAvatar ? (
        <img
          src={avatarUrl}
          alt={queen.name}
          className="w-full h-full object-cover"
          onError={() => setHasAvatar(false)}
        />
      ) : queen.portrait ? (
        <QueenPortraitGlyph p={queen.portrait} className="w-full h-full" />
      ) : (
        <span className="font-bold text-primary leading-none">{queen.name.charAt(0)}</span>
      )}
    </span>
  );
}

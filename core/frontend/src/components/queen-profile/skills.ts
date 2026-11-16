const OPEN = "(（[【";
const CLOSE = ")）]】";
const SEPARATORS = ",，、;；\n";

/**
 * Her skills (profile.yaml `skills`, free text) as separate items: split at commas and enumeration
 * marks outside brackets, so "drawing (ink, watercolour), teasing" is two skills, not three.
 */
export function splitSkills(text: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let current = "";
  for (const ch of text) {
    if (OPEN.includes(ch)) depth += 1;
    else if (CLOSE.includes(ch)) depth = Math.max(0, depth - 1);
    if (depth === 0 && SEPARATORS.includes(ch)) {
      if (current.trim()) out.push(current.trim());
      current = "";
    } else {
      current += ch;
    }
  }
  if (current.trim()) out.push(current.trim());
  return out;
}

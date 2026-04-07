/**
 * Parse XML-style thinking tags from LLM output into structured segments.
 * All thinking tags are merged into unified "thinking" segments regardless
 * of the original tag name (situation, monologue, execution_plan, etc.).
 */

const THINKING_TAGS = ["situation", "monologue", "execution_plan"];

export interface TextSegment {
  type: "text" | "thinking";
  content: string;
}

const TAG_REGEX = new RegExp(
  `<(/?)(${THINKING_TAGS.join("|")})>`,
  "g",
);

/**
 * Parse text containing XML-style thinking tags into segments.
 *
 * Adjacent thinking blocks are merged into a single segment so they
 * render as one collapsible "Reasoning" block in the UI.
 */
export function parseThinkingTags(text: string): TextSegment[] {
  const raw: TextSegment[] = [];
  let lastIndex = 0;
  let insideTag: string | null = null;
  let tagContentStart = 0;

  TAG_REGEX.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = TAG_REGEX.exec(text)) !== null) {
    const isClosing = match[1] === "/";
    const tagName = match[2];

    if (!isClosing && insideTag === null) {
      const before = text.slice(lastIndex, match.index);
      if (before) {
        raw.push({ type: "text", content: before });
      }
      insideTag = tagName;
      tagContentStart = match.index + match[0].length;
    } else if (isClosing && tagName === insideTag) {
      const inner = text.slice(tagContentStart, match.index);
      if (inner.trim()) {
        raw.push({ type: "thinking", content: inner });
      }
      insideTag = null;
      lastIndex = match.index + match[0].length;
    }
  }

  if (insideTag !== null) {
    const inner = text.slice(tagContentStart);
    if (inner.trim()) {
      raw.push({ type: "thinking", content: inner });
    }
  } else {
    const tail = text.slice(lastIndex);
    if (tail) {
      raw.push({ type: "text", content: tail });
    }
  }

  if (raw.length === 0) {
    return [{ type: "text", content: text }];
  }

  // Merge adjacent thinking segments into one.
  // Whitespace-only text between thinking blocks does not break adjacency —
  // e.g. </situation>\n\n<monologue> should produce one "Thinking" block.
  const merged: TextSegment[] = [];
  for (let i = 0; i < raw.length; i++) {
    const seg = raw[i];
    const prev = merged[merged.length - 1];

    // Skip whitespace-only text segments that sit between two thinking segments
    if (
      seg.type === "text" && !seg.content.trim() &&
      prev?.type === "thinking" &&
      raw[i + 1]?.type === "thinking"
    ) {
      continue;
    }

    if (prev && prev.type === "thinking" && seg.type === "thinking") {
      prev.content += "\n" + seg.content;
    } else if (prev && prev.type === seg.type) {
      prev.content += seg.content;
    } else {
      merged.push({ ...seg });
    }
  }

  return merged;
}

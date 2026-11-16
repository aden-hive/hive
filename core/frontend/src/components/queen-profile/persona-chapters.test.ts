import { describe, it, expect } from "vitest";
import { chapterLabel, isUntitled, joinChapters, outline, parseChapters, readingBody, visible, withBody } from "./persona-chapters";

const PERSONA = [
  "**[Output rules]**",
  "- Pure dialogue.",
  "",
  "<hard_invariants>",
  "She never shouts.",
  "</hard_invariants>",
  "",
  "# Fox · The painter",
  "",
  "# <<<VOICE_MUTABLE_START>>>",
  "<hidden_reasoning>",
  "<inner_monologue>",
  "Look first.",
  "</inner_monologue>",
  "</hidden_reasoning>",
  "<stray>",
  "no closing tag",
  "# <<<VOICE_MUTABLE_END>>>",
  "",
].join("\n");

describe("persona chapters", () => {
  it("cut the text into its chapters and put it back byte for byte", () => {
    const chapters = parseChapters(PERSONA);

    expect(joinChapters(chapters)).toBe(PERSONA);
    expect(visible(chapters).map(({ chapter }) => [chapter.kind, chapter.title])).toEqual([
      ["text", "Output rules"],
      ["block", "Hard invariants"],
      ["text", "Fox · The painter"],
      ["marker", "VOICE_MUTABLE_START"],
      ["block", "Hidden reasoning"],
      ["block", "Stray"],
      ["marker", "VOICE_MUTABLE_END"],
    ]);
    expect(chapters.find((c) => c.tag === "hidden_reasoning")?.body).toBe("<inner_monologue>\nLook first.\n</inner_monologue>");
  });

  it("rebuild only the chapter that was edited", () => {
    const chapters = parseChapters(PERSONA);
    const at = chapters.findIndex((c) => c.tag === "hard_invariants");
    chapters[at] = withBody(chapters[at], "She never shouts.\nShe never begs.\r\n");

    expect(joinChapters(chapters)).toBe(PERSONA.replace("She never shouts.\n", "She never shouts.\nShe never begs.\n"));
  });

  it("keep the blank lines around an edited stretch of text", () => {
    const chapters = parseChapters("<a>\nx\n</a>\n\nSome words.\n\n<b>\ny\n</b>");
    const at = chapters.findIndex((c) => c.kind === "text" && c.body === "Some words.");
    chapters[at] = withBody(chapters[at], "Other words.");

    expect(joinChapters(chapters)).toBe("<a>\nx\n</a>\n\nOther words.\n\n<b>\ny\n</b>");
  });

  it("read blocks written on the tag's line, and blocks never closed", () => {
    const text = [
      "<appearance> Long silver hair.",
      "- Amber eyes.",
      "",
      "<instinct_tools> She sniffs things out.",
      "Never says she searched. </instinct_tools>",
      "<offstage_life> Naps at noon.",
      "<voice_core>",
      "Soft.",
      "</voice_core>",
    ].join("\n");
    const chapters = parseChapters(text);

    expect(joinChapters(chapters)).toBe(text);
    expect(visible(chapters).map(({ chapter }) => [chapter.tag, chapter.body])).toEqual([
      ["appearance", "Long silver hair.\n- Amber eyes."],
      ["instinct_tools", "She sniffs things out.\nNever says she searched."],
      ["offstage_life", "Naps at noon."],
      ["voice_core", "Soft."],
    ]);

    const at = chapters.findIndex((c) => c.tag === "appearance");
    chapters[at] = withBody(chapters[at], "Long silver hair.");
    const tools = chapters.findIndex((c) => c.tag === "instinct_tools");
    chapters[tools] = withBody(chapters[tools], "She sniffs things out.");
    expect(joinChapters(chapters)).toBe(
      ["<appearance> Long silver hair.", "", "<instinct_tools> She sniffs things out. </instinct_tools>", "<offstage_life> Naps at noon.", "<voice_core>", "Soft.", "</voice_core>"].join("\n"),
    );
  });

  it("number the chapters and gather what lies between a START and its END marker", () => {
    const items = outline(parseChapters(PERSONA));

    expect(items.map((item) => (item.kind === "region" ? [item.start.chapter.tag, item.entries.map((e) => e.n)] : [item.kind, item.entry.n]))).toEqual([
      ["chapter", 1],
      ["chapter", 2],
      ["chapter", 3],
      ["VOICE_MUTABLE_START", [4, 5]],
    ]);
  });

  it("show a stretch of text without the line that titles it", () => {
    const [rules] = parseChapters("**[Output rules]**\n- Pure dialogue.\n\n<a>\nx\n</a>");

    expect(rules.title).toBe("Output rules");
    expect(readingBody(rules)).toBe("- Pure dialogue.");
    expect(readingBody(parseChapters("Just a plain bio.")[0])).toBe("Just a plain bio.");
  });

  it("title text by a short first line that ends in a colon, and name untitled text by how it begins", () => {
    const [occasions] = parseChapters("Two occasions, the other way round:\n- When teased, tease back.");
    const [plain] = parseChapters("From here on, only how she sounds, never what she must do.");

    expect(occasions.title).toBe("Two occasions, the other way round");
    expect(readingBody(occasions)).toBe("- When teased, tease back.");
    expect(isUntitled(plain)).toBe(true);
    expect(chapterLabel(plain)).toBe("From here on, only…");
    expect(chapterLabel(occasions)).toBe("Two occasions, the other way round");
  });

  it("treat a persona without chapters as one stretch of text", () => {
    expect(parseChapters("Just a plain bio.").map((c) => [c.kind, c.body])).toEqual([["text", "Just a plain bio."]]);
  });
});

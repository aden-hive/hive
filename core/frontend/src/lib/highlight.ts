/**
 * Syntax highlighting for markdown code blocks, loaded on first use.
 *
 * Shiki with its JavaScript regex engine (no WASM, nothing for the CSP to
 * refuse) and a CSS-variables theme, so token colours come from index.css
 * and follow the light/dark palette. Each grammar is its own chunk, fetched
 * the first time a block in that language renders.
 */
import type { HighlighterCore, LanguageInput } from "shiki/core";

type Grammar = () => Promise<{ default: LanguageInput }>;

const GRAMMARS: Record<string, Grammar> = {
  javascript: () => import("shiki/langs/javascript.mjs"),
  jsx: () => import("shiki/langs/jsx.mjs"),
  typescript: () => import("shiki/langs/typescript.mjs"),
  tsx: () => import("shiki/langs/tsx.mjs"),
  json: () => import("shiki/langs/json.mjs"),
  jsonc: () => import("shiki/langs/jsonc.mjs"),
  python: () => import("shiki/langs/python.mjs"),
  bash: () => import("shiki/langs/bash.mjs"),
  powershell: () => import("shiki/langs/powershell.mjs"),
  sql: () => import("shiki/langs/sql.mjs"),
  yaml: () => import("shiki/langs/yaml.mjs"),
  toml: () => import("shiki/langs/toml.mjs"),
  ini: () => import("shiki/langs/ini.mjs"),
  html: () => import("shiki/langs/html.mjs"),
  xml: () => import("shiki/langs/xml.mjs"),
  css: () => import("shiki/langs/css.mjs"),
  scss: () => import("shiki/langs/scss.mjs"),
  markdown: () => import("shiki/langs/markdown.mjs"),
  diff: () => import("shiki/langs/diff.mjs"),
  go: () => import("shiki/langs/go.mjs"),
  rust: () => import("shiki/langs/rust.mjs"),
  java: () => import("shiki/langs/java.mjs"),
  kotlin: () => import("shiki/langs/kotlin.mjs"),
  swift: () => import("shiki/langs/swift.mjs"),
  c: () => import("shiki/langs/c.mjs"),
  cpp: () => import("shiki/langs/cpp.mjs"),
  csharp: () => import("shiki/langs/csharp.mjs"),
  php: () => import("shiki/langs/php.mjs"),
  ruby: () => import("shiki/langs/ruby.mjs"),
  dockerfile: () => import("shiki/langs/dockerfile.mjs"),
  graphql: () => import("shiki/langs/graphql.mjs"),
  lua: () => import("shiki/langs/lua.mjs"),
  r: () => import("shiki/langs/r.mjs"),
};

const ALIASES: Record<string, string> = {
  js: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  node: "javascript",
  ts: "typescript",
  py: "python",
  python3: "python",
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  console: "bash",
  shellscript: "bash",
  ps: "powershell",
  ps1: "powershell",
  pwsh: "powershell",
  yml: "yaml",
  md: "markdown",
  htm: "html",
  svg: "xml",
  golang: "go",
  rs: "rust",
  kt: "kotlin",
  "c++": "cpp",
  cc: "cpp",
  h: "c",
  cs: "csharp",
  "c#": "csharp",
  rb: "ruby",
  docker: "dockerfile",
  gql: "graphql",
  patch: "diff",
  cfg: "ini",
  conf: "ini",
};

/** The grammar name for a fence's language tag, or null when unsupported. */
export function resolveLanguage(tag: string | undefined): string | null {
  if (!tag) return null;
  const key = tag.toLowerCase();
  const name = ALIASES[key] ?? key;
  return name in GRAMMARS ? name : null;
}

let highlighter: Promise<HighlighterCore> | null = null;
const loaded = new Map<string, Promise<void>>();

function getHighlighter(): Promise<HighlighterCore> {
  highlighter ??= (async () => {
    const [{ createHighlighterCore, createCssVariablesTheme }, { createJavaScriptRegexEngine }] = await Promise.all([
      import("shiki/core"),
      import("shiki/engine/javascript"),
    ]);
    return createHighlighterCore({
      themes: [createCssVariablesTheme({ name: "hive", variablePrefix: "--shiki-", fontStyle: true })],
      langs: [],
      engine: createJavaScriptRegexEngine(),
    });
  })();
  return highlighter;
}

/**
 * Highlight `code` as `language` (a value from `resolveLanguage`) and return
 * the HTML of its lines, one `<span class="line">` each. Shiki escapes the
 * source, so the result is safe to inject.
 */
export async function highlightLines(code: string, language: string): Promise<string> {
  const hl = await getHighlighter();
  let ready = loaded.get(language);
  if (!ready) {
    ready = GRAMMARS[language]().then((m) => hl.loadLanguage(m.default));
    loaded.set(language, ready);
  }
  await ready;
  const html = hl.codeToHtml(code, { lang: language, theme: "hive" });
  // Keep only the lines; the block chrome (pre/code, colours) is ours.
  const start = html.indexOf("<code>");
  const end = html.lastIndexOf("</code>");
  return start >= 0 && end > start ? html.slice(start + "<code>".length, end) : html;
}

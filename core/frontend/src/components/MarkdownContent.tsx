import { isValidElement, useEffect, useState, type ReactElement, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import { useNavigate } from "react-router-dom";
import { Check, Copy, Info, Lightbulb, MessageSquareWarning, OctagonAlert, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { parseAppLink } from "@/lib/appLinks";
import { parseThinkingTags } from "@/lib/thinking-tags";
import { highlightLines, resolveLanguage } from "@/lib/highlight";
import ThinkingBlock from "./ThinkingBlock";

/**
 * A link in agent output. `hive://…` links navigate in-app (e.g. an agent
 * handing the user a pre-filled sender form it couldn't finish itself);
 * everything else opens in the browser as before.
 */
function MarkdownLink({
  href,
  children,
}: {
  href?: string;
  children: React.ReactNode;
}) {
  const navigate = useNavigate();
  const appPath = parseAppLink(href);

  if (appPath) {
    return (
      <button type="button" onClick={() => navigate(appPath)} className="hive-md-link text-left">
        {children}
      </button>
    );
  }

  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="hive-md-link">
      {children}
    </a>
  );
}

/** Blocks past this many lines start collapsed. */
const COLLAPSE_AFTER_LINES = 24;
/** Blocks from this many lines get line numbers. */
const NUMBER_FROM_LINES = 10;

const LANGUAGE_NAMES: Record<string, string> = {
  javascript: "JavaScript",
  jsx: "JSX",
  typescript: "TypeScript",
  tsx: "TSX",
  json: "JSON",
  jsonc: "JSONC",
  python: "Python",
  bash: "Shell",
  powershell: "PowerShell",
  sql: "SQL",
  yaml: "YAML",
  toml: "TOML",
  ini: "INI",
  html: "HTML",
  xml: "XML",
  css: "CSS",
  scss: "SCSS",
  markdown: "Markdown",
  diff: "Diff",
  go: "Go",
  rust: "Rust",
  java: "Java",
  kotlin: "Kotlin",
  swift: "Swift",
  c: "C",
  cpp: "C++",
  csharp: "C#",
  php: "PHP",
  ruby: "Ruby",
  dockerfile: "Dockerfile",
  graphql: "GraphQL",
  lua: "Lua",
  r: "R",
};

/** How a diff line reads: added, removed, a hunk header, or context. */
function diffKind(line: string): "add" | "del" | "hunk" | undefined {
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+") && !line.startsWith("+++")) return "add";
  if (line.startsWith("-") && !line.startsWith("---")) return "del";
  return undefined;
}

/** A fenced code block: language header with copy, highlighted body, line
 *  numbers on longer blocks, and a collapse for very long ones. */
function CodeBlock({ code, tag }: { code: string; tag?: string }) {
  const language = resolveLanguage(tag);
  // Diffs read by line, not by token: they get add/remove rows instead of
  // grammar colours.
  const isDiff = language === "diff";
  const [html, setHtml] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!language || isDiff) {
      setHtml(null);
      return;
    }
    let live = true;
    // While a reply streams the block changes every token; wait for a pause.
    const timer = window.setTimeout(() => {
      highlightLines(code, language)
        .then((out) => live && setHtml(out))
        .catch(() => live && setHtml(null));
    }, 90);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [code, language, isDiff]);

  const lines = code.split("\n");
  const collapsible = lines.length > COLLAPSE_AFTER_LINES;
  const collapsed = collapsible && !expanded;
  const label = language ? LANGUAGE_NAMES[language] : tag || "Text";

  const copy = () => {
    void navigator.clipboard?.writeText(code).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    });
  };

  return (
    <div className="hive-code" data-collapsed={collapsed || undefined}>
      <div className="hive-code-head">
        <span className="hive-code-lang">{label}</span>
        <button type="button" className="hive-code-copy" onClick={copy} aria-label="Copy code">
          {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
          <span>{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
      <pre data-numbered={lines.length >= NUMBER_FROM_LINES || undefined}>
        {html !== null ? (
          <code dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <code>
            {lines.map((line, i) => (
              <span key={i}>
                <span className="line" data-diff={isDiff ? diffKind(line) : undefined}>
                  {line}
                </span>
                {i < lines.length - 1 ? "\n" : null}
              </span>
            ))}
          </code>
        )}
      </pre>
      {collapsible && (
        <button type="button" className="hive-code-more" onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Show less" : `Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  );
}

/** Read a fenced block's source and language off the `<code>` child that
 *  react-markdown nests inside `<pre>`. */
function fencedCode(children: ReactNode): { code: string; tag?: string } | null {
  const child = Array.isArray(children) ? children[0] : children;
  if (!isValidElement(child)) return null;
  const props = (child as ReactElement<{ className?: string; children?: ReactNode }>).props;
  const tag = /language-(\S+)/.exec(props.className ?? "")?.[1];
  const code = String(props.children ?? "").replace(/\n$/, "");
  return { code, tag };
}

type CalloutKind = "note" | "tip" | "important" | "warning" | "caution";

const CALLOUTS: Record<CalloutKind, { label: string; Icon: typeof Info }> = {
  note: { label: "Note", Icon: Info },
  tip: { label: "Tip", Icon: Lightbulb },
  important: { label: "Important", Icon: MessageSquareWarning },
  warning: { label: "Warning", Icon: TriangleAlert },
  caution: { label: "Caution", Icon: OctagonAlert },
};

const CALLOUT_MARKER = /^\[!(note|tip|important|warning|caution)\][ \t]*\n?/i;

interface MdNode {
  type: string;
  value?: string;
  children?: MdNode[];
  data?: { hProperties?: Record<string, unknown> };
}

/** GitHub alerts: a blockquote opening with `[!NOTE]` (TIP, IMPORTANT,
 *  WARNING, CAUTION) becomes a callout; the marker itself is removed. */
function remarkCallouts() {
  const visit = (node: MdNode) => {
    if (node.type === "blockquote") {
      const first = node.children?.[0];
      const text = first?.type === "paragraph" ? first.children?.[0] : undefined;
      const match = text?.type === "text" && text.value ? CALLOUT_MARKER.exec(text.value) : null;
      if (text && match) {
        text.value = text.value!.slice(match[0].length);
        node.data = {
          ...node.data,
          hProperties: { ...node.data?.hProperties, "data-callout": match[1].toLowerCase() },
        };
      }
    }
    node.children?.forEach(visit);
  };
  return (tree: MdNode) => visit(tree);
}

const components: Components = {
  pre: ({ children }) => {
    const block = fencedCode(children);
    return block ? <CodeBlock code={block.code} tag={block.tag} /> : <pre>{children}</pre>;
  },

  // Only inline code reaches here: fenced blocks are rendered whole by `pre`.
  code: ({ className, children }) => <code className={className}>{children}</code>,

  // Links — hive:// navigates in-app, everything else opens externally
  a: ({ href, children }) => <MarkdownLink href={href}>{children}</MarkdownLink>,

  table: ({ children }) => (
    <div className="hive-md-table">
      <table>{children}</table>
    </div>
  ),

  blockquote: ({ children, ...props }) => {
    const kind = (props as { "data-callout"?: CalloutKind })["data-callout"];
    if (!kind || !(kind in CALLOUTS)) return <blockquote>{children}</blockquote>;
    const { label, Icon } = CALLOUTS[kind];
    return (
      <div className="hive-md-callout" data-callout={kind}>
        <div className="hive-md-callout-title">
          <Icon className="w-3.5 h-3.5" />
          {label}
        </div>
        {children}
      </div>
    );
  },
};

const remarkPlugins = [remarkGfm, remarkCallouts];

interface MarkdownContentProps {
  content: string;
  className?: string;
  // Per-instance component overrides merged over the defaults. Lets a caller
  // (e.g. the skills drawer) restyle code/pre without affecting chat rendering.
  components?: Partial<Components>;
}

export default function MarkdownContent({
  content,
  className,
  components: overrides,
}: MarkdownContentProps) {
  const merged = overrides ? { ...components, ...overrides } : components;
  const segments = parseThinkingTags(content);

  // Fast path: no thinking tags — render as before
  if (segments.length === 1 && segments[0].type === "text") {
    return (
      <div className={cn("hive-md break-words text-foreground", className)}>
        <ReactMarkdown remarkPlugins={remarkPlugins} components={merged}>
          {content}
        </ReactMarkdown>
      </div>
    );
  }

  return (
    <div className={cn("hive-md break-words text-foreground", className)}>
      {segments.map((seg, i) =>
        seg.type === "thinking" ? (
          <ThinkingBlock key={i} content={seg.content} />
        ) : (
          <ReactMarkdown key={i} remarkPlugins={remarkPlugins} components={merged}>
            {seg.content}
          </ReactMarkdown>
        ),
      )}
    </div>
  );
}

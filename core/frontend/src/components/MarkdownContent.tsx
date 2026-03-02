import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import { cn } from "@/lib/utils";

const components: Components = {
  // Headers: same size as body text, just bold — keeps chat bubbles compact
  h1: ({ children }) => <h1 className="font-bold mt-3 mb-1 first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="font-bold mt-2 mb-1 first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="font-semibold mt-2 mb-1 first:mt-0">{children}</h3>,

  // Paragraphs: preserve whitespace and line breaks (matches existing plain-text behavior)
  p: ({ children }) => <p className="whitespace-pre-wrap break-words mb-2 last:mb-0">{children}</p>,

  // Lists
  ul: ({ children }) => <ul className="list-disc pl-4 mb-2 last:mb-0 space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 last:mb-0 space-y-0.5">{children}</ol>,
  li: ({ children }) => <li>{children}</li>,

  // Inline code
  code: ({ className, children, ...props }) => {
    const isBlock = className?.includes("language-");
    if (isBlock) {
      return (
        <code className={cn("text-xs", className)} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className="bg-muted px-1 py-0.5 rounded text-[13px] font-mono">
        {children}
      </code>
    );
  },

  // Code blocks
  pre: ({ children }) => (
    <pre className="bg-muted/80 rounded-lg p-3 overflow-x-auto text-xs font-mono my-2 last:mb-0">
      {children}
    </pre>
  ),

  // Links
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary underline underline-offset-2 hover:opacity-80"
    >
      {children}
    </a>
  ),

  // Tables
  table: ({ children }) => (
    <div className="overflow-x-auto my-2 last:mb-0">
      <table className="text-xs border-collapse w-full">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-border px-2 py-1 text-left font-semibold bg-muted/40">
      {children}
    </th>
  ),
  td: ({ children }) => <td className="border border-border px-2 py-1">{children}</td>,

  // Blockquotes
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-primary/40 pl-3 my-2 text-muted-foreground italic">
      {children}
    </blockquote>
  ),

  // Horizontal rules
  hr: () => <hr className="border-border my-3" />,

  // Strong & emphasis inherit naturally from <strong>/<em> defaults — no overrides needed
};

const remarkPlugins = [remarkGfm];

interface MarkdownContentProps {
  content: string;
  className?: string;
}

export default function MarkdownContent({ content, className }: MarkdownContentProps) {
  return (
    <div className={cn("break-words text-foreground", className)}>
      <ReactMarkdown remarkPlugins={remarkPlugins} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

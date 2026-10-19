import ReactDOMServer from "react-dom/server";
import { createElement } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => {
    switch (c) {
      case "&": return "&amp;";
      case "<": return "&lt;";
      case ">": return "&gt;";
      case '"': return "&quot;";
      case "'": return "&#39;";
      default: return c;
    }
  });
}

const PRINT_CSS = `
@page { margin: 22mm 20mm; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: #1a1a1a;
  font-size: 11.5pt;
  line-height: 1.55;
  margin: 0;
  padding: 0;
}
.doc-header { border-bottom: 1px solid #e3e3e3; padding-bottom: 10px; margin-bottom: 18px; }
.doc-title { font-size: 16pt; font-weight: 600; margin: 0; }
.doc-meta { color: #888; font-size: 9.5pt; margin-top: 4px; }
h1 { font-size: 18pt; margin: 22px 0 8px; }
h2 { font-size: 14pt; margin: 18px 0 6px; }
h3 { font-size: 12pt; margin: 14px 0 4px; }
p { margin: 0 0 10px; }
ul, ol { padding-left: 24px; margin: 0 0 10px; }
li { margin: 3px 0; }
code {
  font-family: Menlo, Consolas, "SF Mono", monospace;
  font-size: 10pt;
  background: #f3f4f6;
  padding: 1px 4px;
  border-radius: 3px;
}
pre {
  background: #f6f8fa;
  border: 1px solid #e3e6ea;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 10pt;
  margin: 0 0 12px;
}
pre code { background: transparent; padding: 0; border: 0; }
blockquote {
  border-left: 3px solid #d4d4d4;
  padding: 0 12px;
  margin: 0 0 12px;
  color: #555;
}
a { color: #1364c6; }
table { border-collapse: collapse; width: 100%; margin: 0 0 12px; font-size: 10.5pt; }
th, td { border: 1px solid #d8dade; padding: 5px 8px; text-align: left; vertical-align: top; }
th { background: #f5f6f7; font-weight: 600; }
hr { border: 0; border-top: 1px solid #e3e3e3; margin: 16px 0; }
img { max-width: 100%; }
`;

interface BuildPrintableOptions {
  /** Document title shown in the PDF header and used as default filename. */
  title: string;
  /** Optional subtitle line (e.g. queen name + timestamp). */
  meta?: string;
}

/**
 * Convert a queen response (markdown string) into a fully self-contained
 * HTML document suitable for browser print-to-PDF. Renders the markdown
 * via the same react-markdown + remark-gfm pipeline used in-app, but
 * without any in-app className styling — semantic tags only, styled by the
 * print CSS above. Returns a string ready to hand to the print shim.
 */
export function buildPrintableHtml(
  markdown: string,
  options: BuildPrintableOptions,
): string {
  const body = ReactDOMServer.renderToStaticMarkup(
    createElement(ReactMarkdown, { remarkPlugins: [remarkGfm] }, markdown),
  );
  const title = escapeHtml(options.title);
  const meta = options.meta ? escapeHtml(options.meta) : "";
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>${title}</title>
<style>${PRINT_CSS}</style>
</head>
<body>
<div class="doc-header">
  <h1 class="doc-title">${title}</h1>
  ${meta ? `<div class="doc-meta">${meta}</div>` : ""}
</div>
${body}
</body>
</html>`;
}

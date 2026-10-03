/**
 * Markdown panel: a small, safe Markdown subset rendered as React elements.
 *
 * Supported: paragraphs (single newlines become line breaks), `#`-`###` headings, `-`/`*`
 * and `1.` lists, fenced code, `---` rules, `**bold**`, `*italic*`, `` `code` `` and
 * `[text](url)` links. Raw HTML is never interpreted: React escapes it, so it shows as text.
 * Links keep only http(s), mailto, relative and `#` targets.
 */
import type { CSSProperties, ReactNode } from "react";
import type { PanelResult } from "./index";

/** One parsed block of Markdown. */
export type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "h"; level: 1 | 2 | 3; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "code"; text: string }
  | { kind: "hr" };

const FENCE = /^\s*```/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const RULE = /^\s*(-{3,}|\*{3,})\s*$/;
const LIST = { ul: /^\s*[-*+]\s+(.*)$/, ol: /^\s*\d+[.)]\s+(.*)$/ } as const;

function isBlockStart(line: string): boolean {
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    RULE.test(line) ||
    LIST.ul.test(line) ||
    LIST.ol.test(line)
  );
}

/** Split Markdown source into blocks. */
export function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") {
      i++;
      continue;
    }
    if (FENCE.test(line)) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !FENCE.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push({ kind: "code", text: body.join("\n") });
      continue;
    }
    const h = HEADING.exec(line);
    if (h) {
      out.push({ kind: "h", level: Math.min(h[1].length, 3) as 1 | 2 | 3, text: h[2].trim() });
      i++;
      continue;
    }
    if (RULE.test(line)) {
      out.push({ kind: "hr" });
      i++;
      continue;
    }
    const kind = LIST.ul.test(line) ? "ul" : LIST.ol.test(line) ? "ol" : null;
    if (kind) {
      const items: string[] = [];
      while (i < lines.length) {
        const m = LIST[kind].exec(lines[i]);
        if (!m) break;
        items.push(m[1]);
        i++;
      }
      out.push({ kind, items });
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() !== "" && !isBlockStart(lines[i])) {
      para.push(lines[i].trim());
      i++;
    }
    out.push({ kind: "p", lines: para });
  }
  return out;
}

/**
 * Return a link target if it is safe to render, else `null`.
 *
 * The target is cleaned the way a URL parser reads it first (leading and trailing C0
 * controls and spaces dropped, tabs and newlines removed anywhere), so a scheme cannot
 * hide behind them. Web and mail links pass; other schemes and protocol-relative links
 * (`//`, or `\\` which browsers read as `/`) do not.
 */
export function safeHref(url: string): string | null {
  const u = url.replace(/^[\x00-\x20]+|[\x00-\x20]+$/g, "").replace(/[\t\n\r]/g, "");
  if (/^(https?:|mailto:)/i.test(u)) return u;
  if (/^[a-z][a-z0-9+.-]*:/i.test(u)) return null;
  if (/^[\\/]{2}/.test(u)) return null;
  return u;
}

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\[[^\]\n]+\]\([^)\s]+\))|(\*[^*\s][^*\n]*\*)/;
const LINK = /^\[([^\]]+)\]\(([^)\s]+)\)$/;

const S = {
  notes: {
    font: "400 17px/1.6 var(--serif)",
    color: "var(--ink-2)",
    textWrap: "pretty",
  },
  p: { margin: "0 0 8px" },
  h: { font: "600 16px/1.3 var(--sans)", color: "var(--ink)", margin: "12px 0 6px" },
  b: { color: "var(--ink)", fontWeight: 650 },
  code: {
    fontFamily: "var(--mono)",
    fontSize: ".86em",
    background: "var(--paper-2)",
    borderRadius: 3,
    padding: "1px 4px",
  },
  pre: {
    font: "400 13px/1.6 var(--mono)",
    color: "var(--ink)",
    background: "var(--paper-2)",
    borderRadius: 6,
    padding: "10px 12px",
    margin: "0 0 8px",
    whiteSpace: "pre-wrap",
  },
  list: { margin: "0 0 8px", paddingLeft: 22 },
  hr: { border: 0, borderTop: "1px solid var(--rule)", margin: "12px 0" },
  empty: { fontSize: 13, color: "var(--ink-3)", margin: 0 },
} satisfies Record<string, CSSProperties>;

/** Render inline Markdown (code, bold, italic, links) as React nodes. */
export function renderInline(text: string, key = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text;
  let n = 0;
  while (rest) {
    const m = INLINE.exec(rest);
    if (!m) {
      out.push(rest);
      break;
    }
    if (m.index > 0) out.push(rest.slice(0, m.index));
    const tok = m[0];
    const k = `${key}.${n++}`;
    if (m[1]) {
      out.push(
        <code key={k} style={S.code}>
          {tok.slice(1, -1)}
        </code>,
      );
    } else if (m[2]) {
      out.push(
        <b key={k} style={S.b}>
          {renderInline(tok.slice(2, -2), k)}
        </b>,
      );
    } else if (m[3]) {
      const lm = LINK.exec(tok);
      const href = lm ? safeHref(lm[2]) : null;
      const inner = renderInline(lm ? lm[1] : tok, k);
      if (href === null) out.push(<span key={k}>{inner}</span>);
      else if (/^https?:/i.test(href)) {
        out.push(
          <a key={k} href={href} target="_blank" rel="noreferrer noopener">
            {inner}
          </a>,
        );
      } else
        out.push(
          <a key={k} href={href}>
            {inner}
          </a>,
        );
    } else {
      out.push(<i key={k}>{renderInline(tok.slice(1, -1), k)}</i>);
    }
    rest = rest.slice(m.index + tok.length);
  }
  return out;
}

function renderBlock(b: Block, i: number): ReactNode {
  const k = String(i);
  switch (b.kind) {
    case "p":
      return (
        <p key={k} style={S.p}>
          {b.lines.flatMap((line, j) => {
            const inline = renderInline(line, `${k}.${j}`);
            return j === 0 ? inline : [<br key={`${k}.br${j}`} />, ...inline];
          })}
        </p>
      );
    case "h": {
      const Tag = (["h3", "h4", "h5"] as const)[b.level - 1];
      return (
        <Tag key={k} style={S.h}>
          {renderInline(b.text, k)}
        </Tag>
      );
    }
    case "ul":
    case "ol": {
      const Tag = b.kind;
      return (
        <Tag key={k} style={S.list}>
          {b.items.map((item, j) => (
            <li key={j}>{renderInline(item, `${k}.${j}`)}</li>
          ))}
        </Tag>
      );
    }
    case "code":
      return (
        <pre key={k} style={S.pre}>
          <code>{b.text}</code>
        </pre>
      );
    case "hr":
      return <hr key={k} style={S.hr} />;
  }
}

/** Markdown panel. Reads `result.meta.text`. */
export function MarkdownPanel({ result }: { result: PanelResult }) {
  const meta = (result.meta ?? {}) as Record<string, unknown>;
  const text = typeof meta.text === "string" ? meta.text : "";
  if (!text.trim()) return <p style={S.empty}>No text</p>;
  return (
    <div className="notes" style={S.notes}>
      {parseBlocks(text).map(renderBlock)}
    </div>
  );
}

export default MarkdownPanel;

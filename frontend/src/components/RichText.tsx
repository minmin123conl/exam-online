import React from "react";
import { API_BASE } from "../api";

/**
 * Renders question/option text that may include inline markers:
 *   [IMG:<url>]    -> <img src=...>
 *   [MATH:<text>]  -> <span class="formula">...</span>
 *
 * URLs starting with "/uploads/" are resolved relative to the API base.
 */
export function RichText({ text, className }: { text: string | null | undefined; className?: string }) {
  if (!text) return null;
  const re = /\[(IMG|MATH):([^\]]+)\]/g;
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      nodes.push(text.slice(last, m.index));
    }
    if (m[1] === "IMG") {
      const url = m[2].startsWith("http") ? m[2] : m[2].startsWith("/") ? `${API_BASE}${m[2]}` : m[2];
      nodes.push(
        <img
          key={`img-${key++}`}
          src={url}
          alt=""
          className="rt-img"
          loading="lazy"
        />,
      );
    } else if (m[1] === "MATH") {
      nodes.push(
        <span key={`math-${key++}`} className="rt-formula" title="Công thức (OMML)">
          {m[2]}
        </span>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    nodes.push(text.slice(last));
  }
  return <span className={className}>{nodes}</span>;
}

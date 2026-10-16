/** File rows (mockup .files): icon, name, path, size, copy on hover. */
import { CopyButton } from "../pages/components/CopyButton";
import { fmtBytes } from "../pages/components/format";
import { AppLink } from "../pages/components/links";
import type { FileIcon, FileRow } from "./files";

const GLYPH: Record<FileIcon, string> = {
  folder: "M2 4.5h4l1.5 1.5H14v6.5H2z",
  doc: "M4 2h5l3 3v9H4zM9 2v3h3",
  box: "M2.5 5 8 2l5.5 3v6L8 14l-5.5-3zM2.5 5 8 8l5.5-3M8 8v6",
};

function FileGlyph({ kind }: { kind: FileIcon }) {
  return (
    <svg className="ficon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path d={GLYPH[kind]} fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  );
}

export function FileList({ rows }: { rows: FileRow[] }) {
  if (rows.length === 0) return <p className="muted">No run folder recorded</p>;
  return (
    <ul className="files">
      {rows.map((row, i) => (
        <li key={`${row.copy}-${i}`} className="file">
          <FileGlyph kind={row.icon} />
          <span className="fn" title={row.note}>
            <span className="fname">{row.href ? <AppLink href={row.href}>{row.name}</AppLink> : row.name}</span>
            {row.note ? <small>{row.note}</small> : null}
          </span>
          <span className="fp mono" title={row.copy}>
            {row.path}
          </span>
          <span className="fs">{row.size !== null ? fmtBytes(row.size) : ""}</span>
          <CopyButton text={row.copy} label={row.name} />
        </li>
      ))}
    </ul>
  );
}

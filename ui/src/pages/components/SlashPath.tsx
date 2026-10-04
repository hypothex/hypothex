import { Fragment } from "react";

/** Inline-safe path with wrap opportunities only after `/`; its text stays exact. */
export function SlashPath({ path, title, className }: { path: string; title?: string; className?: string }) {
  const parts = path.split("/");
  return (
    <span className={className} title={title} style={{ wordBreak: "normal", overflowWrap: "normal", whiteSpace: "normal" }}>
      {parts.map((part, i) => (
        <Fragment key={i}>
          <span style={{ whiteSpace: "nowrap" }}>{part}{i < parts.length - 1 ? "/" : ""}</span>
          {i < parts.length - 1 ? <wbr /> : null}
        </Fragment>
      ))}
    </span>
  );
}

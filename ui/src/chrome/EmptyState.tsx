/** One calm block for "nothing here yet" and "loading" (mockup `.empty`). */
import { type ReactElement, type ReactNode } from "react";
import "./chrome.css";

export interface EmptyCommand {
  /** "1", "2", "or". */
  n: string;
  cmd: string;
  what: string;
}

export interface EmptyStateProps {
  title?: string;
  body?: ReactNode;
  commands?: readonly EmptyCommand[];
  links?: readonly { label: string; href: string }[];
  loading?: boolean;
}

export function EmptyState({ title, body, commands = [], links = [], loading = false }: EmptyStateProps): ReactElement {
  if (loading) {
    return (
      <div className="empty" role="status">
        <div className="spin-lg" aria-hidden="true" />
        {body ? <p>{body}</p> : null}
      </div>
    );
  }
  return (
    <div className="empty">
      {title ? <h2>{title}</h2> : null}
      {body ? <p>{body}</p> : null}
      {commands.length > 0 ? (
        <ol className="cmds">
          {commands.map((c) => (
            <li className="ecmd" key={c.cmd}>
              <span className="n">{c.n}</span>
              <code title={c.cmd}>{c.cmd}</code>
              <span className="what">{c.what}</span>
            </li>
          ))}
        </ol>
      ) : null}
      {links.length > 0 ? (
        <div className="links">
          {links.map((l) => (
            <a key={l.href} href={l.href}>
              {l.label}
            </a>
          ))}
        </div>
      ) : null}
    </div>
  );
}

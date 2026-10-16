/** Home before the first run (spec 4.1): three commands and three links, nothing else. */
import type { ReactElement } from "react";
import { CopyButton } from "../pages/components/CopyButton";
import "./home.css";

const DOCS = "https://github.com/hypothex/hypothex/blob/main/docs/";

export const FIRST_COMMANDS = [
  { n: "1", cmd: "hx init", what: "write hypothex.yaml for this project" },
  { n: "2", cmd: 'hx run -t TASK -H "why this run exists" -- python train.py', what: "record a run" },
  { n: "or", cmd: "hx demo --with-hosts", what: "try it with generated data" },
] as const;

export const HOME_LINKS = [
  { label: "Docs", href: `${DOCS}getting_started.rst` },
  { label: "Agent skill (Claude Code, Codex)", href: `${DOCS}agents.rst` },
  { label: "Add a GPU host", href: `${DOCS}remote.rst` },
] as const;

export function EmptyHome(): ReactElement {
  return (
    <div className="home-empty">
      <h2>No runs yet</h2>
      <p>Hypothex records every run your agents and you launch. Start with one of these.</p>
      <div className="cmds">
        {FIRST_COMMANDS.map((c) => (
          <div key={c.cmd} className="cmd">
            <span className="n">{c.n}</span>
            <span className="c" title={c.cmd}>
              {c.cmd}
            </span>
            <span className="what">{c.what}</span>
            <CopyButton text={c.cmd} label={c.cmd} />
          </div>
        ))}
      </div>
      <div className="links">
        {HOME_LINKS.map((l) => (
          <a key={l.label} href={l.href} target="_blank" rel="noreferrer">
            {l.label}
          </a>
        ))}
      </div>
    </div>
  );
}

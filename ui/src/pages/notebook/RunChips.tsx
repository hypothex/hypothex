import { Fragment } from "react";
import type { RunChip } from "../../api/models";
import { AppLink, hrefs } from "../components/links";
import { runSegments } from "./model";
export function RunChips({ text, runs }: { text: string; runs: RunChip[] }) {
  return <>{runSegments(text).map((part, i) => {
    if (!part.runId) return <Fragment key={i}>{part.text}</Fragment>;
    const chip = runs.find((r) => r.run_id === part.runId);
    if (!chip || !chip.status) return <span key={i} className="notebook-chip unknown" aria-disabled="true">? {part.runId}</span>;
    return <AppLink key={i} className="notebook-chip" href={hrefs.run(part.runId)} title={`${chip.status}${chip.primary === null ? "" : ` · ${chip.primary}`}`}>{chip.label}<small>{chip.status}{chip.primary === null ? "" : ` · ${chip.primary}`}</small></AppLink>;
  })}</>;
}

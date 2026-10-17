import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { auth } from "../../api/auth";
import type { CleanPlan, CleanPolicy, CleanResult } from "../../api/models";
import { PanelSection } from "../../chrome/PanelSection";
import { CleanupDialog } from "./CleanupDialog";
import { useIntent } from "../settings/intent";
import { bytes, confirmBytes, planLive, policy, policyIdentity } from "./model";
interface Frozen { plan: CleanPlan; policy: string; generation: number }
export function Clean({ project, remote = true, localHost, ready }: { project?: string; remote?: boolean; localHost?: string; ready: boolean }) {
  const [days, setDays] = useState("30"); const [kinds, setKinds] = useState(["checkpoint"]); const [pulled, setPulled] = useState(true);
  const [plan, setPlan] = useState<Frozen | null>(null); const [dialog, setDialog] = useState<Frozen | null>(null); const [confirmation, setConfirmation] = useState("");
  const [result, setResult] = useState<CleanResult | null>(null); const [now, setNow] = useState(Date.now()); const client = useQueryClient();
  const configured = policy(days, kinds, pulled, project);
  if (configured && !remote) configured.hosts = localHost ? [localHost] : [];
  const policyKey = policyIdentity(configured);
  const dry = useIntent((body: CleanPolicy, opts) => api.cleanPlan(body, opts), (data, body) => { setPlan({ plan: data, policy: policyIdentity(body), generation: auth.snapshot().generation }); setResult(null); });
  const apply = useIntent((body: { plan_id: string; confirm_bytes: number }, opts) => api.cleanApply(body.plan_id, body.confirm_bytes, opts), (data) => {
    setResult(data); setDialog(null); setPlan(null); setConfirmation("");
    for (const family of ["storage", "run", "runs", "taskRuns", "leaderboard", "views"]) void client.invalidateQueries({ queryKey: [family] });
  });
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(timer); }, []);
  useEffect(() => { setPlan(null); setDialog(null); setResult(null); setConfirmation(""); dry.reset(); }, [policyKey, dry.generation]);
  const matches = (frozen: Frozen | null): frozen is Frozen => !!frozen && ready && auth.current(frozen.generation) && frozen.policy === policyKey && policyIdentity(frozen.plan.policy) === frozen.policy && planLive(frozen.plan, Date.now()) && frozen.plan.items.length > 0;
  const canApply = matches(plan) && !dry.pending && !apply.pending;
  const busy = dry.pending || apply.pending || !!dialog;
  return <PanelSection title="Clean" grid="wide"><div className="phase3-section">
    <p>Only archived, unstarred, ended runs are eligible. The server rechecks every path before deletion. Run metadata and scores are preserved.</p>
    <form onSubmit={(e) => { e.preventDefault(); if (configured && ready && !busy && (remote || localHost)) { setPlan(null); setResult(null); void dry.run(configured); } }}><div className="phase3-fields">
      <label>Older than (days)<input value={days} inputMode="numeric" disabled={busy} onChange={(e) => setDays(e.target.value)} /></label>
      {["checkpoint", "*"].map((kind) => <label key={kind}><input type="checkbox" checked={kinds.includes(kind)} disabled={busy} onChange={(e) => setKinds(e.target.checked ? [...kinds, kind] : kinds.filter((k) => k !== kind))} />{kind === "*" ? "All artifact kinds" : "Checkpoints"}</label>)}
      <label><input type="checkbox" checked={pulled} disabled={busy} onChange={(e) => setPulled(e.target.checked)} />Include pulled copies</label><button className="btn" disabled={!configured || !ready || busy || (!remote && !localHost)}>Dry run</button>
    </div></form>
    {!ready ? <p>Wait for a current authorized storage report before creating a plan.</p> : null}
    {dry.error ? <p role="alert">{dry.error.message}</p> : null}
    {plan ? <div><h3>Plan {plan.plan.plan_id}</h3><p>{bytes(plan.plan.total_bytes)} · {plan.plan.total_bytes} exact bytes · {plan.plan.items.length} candidates · {plan.plan.refused.length} refused</p><p>Created {plan.plan.created_at} · Expires {plan.plan.expires_at}</p><p>Policy: {plan.plan.policy.older_than_days} days · {plan.plan.policy.kinds.join(", ")} · Pulled: {plan.plan.policy.include_pulled ? "yes" : "no"}</p>
      <div className="phase3-scroll"><table aria-label="Plan items"><thead><tr><th>Run</th><th>Host / environment</th><th>Path</th><th>Bytes</th><th>Reason</th></tr></thead><tbody>{plan.plan.items.map((item, i) => <tr key={i}><td>{item.run_id}</td><td>{item.host} · {item.environment_id}</td><td className="storage-path">{item.path}</td><td>{item.bytes}</td><td>{item.reason}</td></tr>)}</tbody></table></div>
      <ul aria-label="Refused items">{plan.plan.refused.map((item, i) => <li key={i}>{item.host} {item.path} {item.run_id}: {item.reason}</li>)}</ul>
      {!planLive(plan.plan, now) ? <p role="alert">Plan expired or invalid; run a new dry run.</p> : null}
      <button className="btn" disabled={!canApply} onClick={() => { if (canApply) { setDialog(structuredClone(plan)); setConfirmation(""); } }}>Apply</button>
    </div> : null}
    {dialog ? <CleanupDialog pending={apply.pending} onClose={() => { if (!apply.pending) { setDialog(null); setConfirmation(""); } }}><p>{bytes(dialog.plan.total_bytes)} · <strong>{dialog.plan.total_bytes} exact bytes</strong></p><p>{dialog.plan.items.length} items · {new Set(dialog.plan.items.map((i) => i.environment_id)).size} environments · {dialog.plan.refused.length} refused</p><p>Plan {dialog.plan.plan_id} · expires {dialog.plan.expires_at}</p>
      <label>Confirm bytes<input value={confirmation} inputMode="numeric" disabled={apply.pending} onChange={(e) => setConfirmation(e.target.value)} /></label>
      {!planLive(dialog.plan, now) ? <p role="alert">Plan expired. Create a new dry run.</p> : null}
      {apply.error ? <p role="alert">{apply.error.message}</p> : null}
      <button className="btn" disabled={apply.pending || !matches(dialog) || !confirmBytes(confirmation, dialog.plan, now)} onClick={() => { if (!apply.pending && matches(dialog) && confirmBytes(confirmation, dialog.plan, Date.now()) && dialog.plan.plan_id === plan?.plan.plan_id) void apply.run({ plan_id: dialog.plan.plan_id, confirm_bytes: dialog.plan.total_bytes }); }}>{apply.pending ? "Applying…" : "Apply"}</button>
    </CleanupDialog> : null}
    {result ? <section aria-label="Cleanup result"><h3>{result.errors.length || result.skipped.length ? "Cleanup completed with skipped items or errors" : "Cleanup completed"}</h3><p>Freed {bytes(result.freed_bytes)} · {result.freed_bytes} bytes</p><h4>Deleted</h4><ul>{result.deleted.map((item, i) => <li key={i}>{item.run_id} · {item.host} · {item.environment_id} · {item.path} · {item.bytes} bytes</li>)}</ul><h4>Skipped</h4><ul>{result.skipped.map((item, i) => <li key={i}>{String(item.host ?? "")} {String(item.path ?? "")}: {String(item.reason ?? "Unknown reason")}</li>)}</ul><h4>Errors</h4><ul>{result.errors.map((item, i) => <li key={i}>{item.host} {item.path}: {item.error ?? item.reason}</li>)}</ul></section> : null}
  </div></PanelSection>;
}

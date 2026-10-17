import { useState, useSyncExternalStore } from "react";
import { auth } from "../api/auth";
import { useHubEnvironment, useMe, useStorage } from "../api/queries";
import { StorageBars } from "./storage/StorageBars";
import { LargestItems } from "./storage/LargestItems";
import { Clean } from "./storage/Clean";
import { bytes } from "./storage/model";
import "./settings/settings.css";
import "./storage/storage.css";
export function StoragePage() {
  const me = useMe(); const p = me.data; const generation = useSyncExternalStore(auth.subscribe, auth.snapshot).generation;
  const allowed = !!p && p.auth !== "legacy" && p.scope === "admin" && !me.error;
  const [project, setProject] = useState(""); const [remote, setRemote] = useState(true);
  const report = useStorage(project || undefined, remote, { enabled: allowed }); const hub = useHubEnvironment({ enabled: allowed });
  const data = report.data;
  const hubId = typeof hub.data?.environment_id === "string" ? hub.data.environment_id : null;
  return <div className="phase3-page"><h1>Storage</h1>{me.isPending ? <p role="status">Loading permissions…</p> : me.error ? <p role="alert">{me.error.message}</p> : !allowed ? <p>Storage requires admin scope.</p> : <>
    <div className="phase3-fields"><label>Project filter<input value={project} onChange={(e) => setProject(e.target.value)} /></label><label><input type="checkbox" checked={remote} onChange={(e) => setRemote(e.target.checked)} />Include remote storage</label></div>
    {report.isPending ? <p role="status">Loading storage…</p> : null}{report.error ? <p role="alert">{report.error.message}</p> : null}
    {data ? <><p>{data.errors.length ? "Partial total" : "Total"}: {bytes(data.total_bytes)} · {data.total_bytes} bytes</p>{data.errors.map((e, i) => <p role="alert" key={i}>{e.host}: {e.error}</p>)}<StorageBars report={data} hub={hubId} /><LargestItems items={data.items} hub={hubId} /></> : null}
    <Clean key={`${generation}:${project}:${remote}`} project={project || undefined} remote={remote} localHost={data?.items.find((item) => item.environment_id === hubId)?.host} ready={allowed && !!data && !report.isFetching && !report.error} />
  </>}</div>;
}

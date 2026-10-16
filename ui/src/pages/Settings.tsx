import { useSyncExternalStore } from "react";
import { auth } from "../api/auth";
import { useMe } from "../api/queries";
import { Sessions } from "./settings/Sessions";
import { Users } from "./settings/Users";
import { AddDevice } from "./settings/AddDevice";
import { Notifications } from "./settings/Notifications";
import "./settings/settings.css";
export function SettingsPage() {
  const me = useMe(); const generation = useSyncExternalStore(auth.subscribe, auth.snapshot).generation;
  const p = me.data;
  return <div className="phase3-page"><h1>Settings</h1>{me.isPending ? <p role="status">Loading permissions…</p> : me.error ? <p role="alert">{me.error.message}</p> : !p || p.auth === "legacy" ? <p>Scoped settings are unavailable on this hub.</p> : <div key={generation}>
    {p.auth === "on" ? <><p>@{p.user} · {p.scope}</p><Sessions principal={p} />{p.scope === "admin" ? <Users principal={p} /> : null}<AddDevice principal={p} /></> : <p>Scoped authentication is off.</p>}
    {p.scope === "admin" ? <Notifications /> : null}
  </div>}</div>;
}

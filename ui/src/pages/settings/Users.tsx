import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { auth } from "../../api/auth";
import type { Principal } from "../../api/models";
import { useUsers } from "../../api/queries";
import { PanelSection } from "../../chrome/PanelSection";
import { useIntent } from "./intent";
export function Users({ principal }: { principal: Principal }) {
  const query = useUsers({ enabled: principal.scope === "admin" && principal.auth === "on" });
  const client = useQueryClient();
  const action = useIntent((name: string, opts) => api.disableUser(name, opts), (_, name) => {
    if (name === principal.user) auth.lock(auth.snapshot().generation);
    else { void client.invalidateQueries({ queryKey: ["auth", "users"] }); void client.invalidateQueries({ queryKey: ["auth", "sessions"] }); }
  });
  return <PanelSection title="Users" grid="wide"><div className="phase3-section">
    {query.isPending ? <p role="status">Loading users…</p> : query.error ? <p role="alert">{query.error.message}</p> : !query.data?.length ? <p>No users</p> : <div className="phase3-scroll"><table aria-label="Users"><thead><tr><th>User</th><th>Role</th><th>Created by</th><th>State</th><th>Action</th></tr></thead><tbody>{query.data.map((u) => <tr key={u.name}><td>{u.name}</td><td>{u.role}</td><td>{u.created_by}</td><td>{u.disabled_at ? `Disabled ${u.disabled_at}` : "Enabled"}</td><td><button className="btn" disabled={!!u.disabled_at || action.pending} onClick={() => void action.run(u.name)}>Disable {u.name}</button></td></tr>)}</tbody></table></div>}
    {action.error ? <p role="alert">{action.error.message}</p> : null}
  </div></PanelSection>;
}

import { useEffect, useRef, useState } from "react";
import { auth } from "../../api/auth";
import { api } from "../../api/client";
import type { PairingOffer, Principal, Scope } from "../../api/models";
import { useUsers } from "../../api/queries";
import { PanelSection } from "../../chrome/PanelSection";
import { allowedScopes, validUser } from "./model";
import { useIntent } from "./intent";
interface OfferIntent { user: string; new_user: boolean; scope: Scope; ttl_seconds: number }
export function AddDevice({ principal }: { principal: Principal }) {
  const users = useUsers({ enabled: principal.scope === "admin" && principal.auth === "on" });
  const [user, setUser] = useState(principal.user ?? ""); const [newName, setNewName] = useState("");
  const [scope, setScope] = useState<Scope>("read"); const [now, setNow] = useState(Date.now());
  const [offer, setOffer] = useState<{ data: PairingOffer; intent: OfferIntent; generation: number } | null>(null);
  const [copy, setCopy] = useState(""); const mounted = useRef(true);
  const offerRef = useRef(offer); offerRef.current = offer;
  const action = useIntent((body: OfferIntent, opts) => api.pairings(body, opts), (data, intent) => setOffer({ data, intent, generation: auth.snapshot().generation }), { retry: false });
  useEffect(() => { mounted.current = true; const timer = setInterval(() => setNow(Date.now()), 1000); return () => { clearInterval(timer); mounted.current = false; }; }, []);
  useEffect(() => { setOffer(null); setCopy(""); }, [action.generation]);
  useEffect(() => { if (offer && Date.parse(offer.data.expires_at) <= now) { setOffer(null); setCopy("Offer expired; create a fresh offer."); } }, [offer, now]);
  const existing = users.data?.find((u) => u.name === user);
  const scopes = allowedScopes(principal, existing);
  const effective = scopes.includes(scope) ? scope : scopes[0];
  const creating = user === "+new"; const selected = creating ? newName : user;
  const valid = !!effective && !!selected && (creating ? validUser(newName, users.data) : principal.scope === "admin" ? !!existing && !existing.disabled_at : selected === principal.user) && (principal.scope === "admin" ? !users.isPending && !users.error : selected === principal.user);
  const alive = offer && auth.current(offer.generation) && Date.parse(offer.data.expires_at) > now;
  const doCopy = async (): Promise<void> => {
    if (!alive || !offer) return; const captured = offer;
    try { await navigator.clipboard.writeText(captured.data.url); if (mounted.current && offerRef.current === captured && auth.current(captured.generation) && Date.parse(captured.data.expires_at) > Date.now()) setCopy("Copied"); }
    catch { if (mounted.current && offerRef.current === captured && auth.current(captured.generation)) setCopy("Clipboard unavailable; select the URL to copy."); }
  };
  return <PanelSection title="Add device" grid="wide"><div className="phase3-section">
    <form onSubmit={(e) => { e.preventDefault(); if (valid && !action.pending) { setOffer(null); setCopy(""); void action.run({ user: selected, new_user: creating, scope: effective!, ttl_seconds: 300 }); } }}>
      <div className="phase3-fields"><label>User <select value={user} disabled={action.pending} onChange={(e) => setUser(e.target.value)}>{principal.scope === "admin" ? <>{users.data?.filter((u) => !u.disabled_at).map((u) => <option key={u.name} value={u.name}>{u.name}</option>)}<option value="+new">+ new</option></> : <option value={principal.user ?? ""}>{principal.user}</option>}</select></label>
      {creating ? <label>New user <input value={newName} disabled={action.pending} onChange={(e) => setNewName(e.target.value)} /></label> : null}
      <label>Device scope <select value={effective ?? ""} disabled={action.pending} onChange={(e) => setScope(e.target.value as Scope)}>{scopes.map((s) => <option key={s}>{s}</option>)}</select></label><button className="btn" disabled={!valid || action.pending}>Create pairing link</button></div>
    </form>
    {users.error && principal.scope === "admin" ? <p role="alert">{users.error.message}</p> : null}
    {action.error ? <p role="alert">{action.error.message}</p> : null}
    {alive && offer ? <div><p>{offer.intent.user} · {offer.intent.scope} · expires {offer.data.expires_at} ({Math.max(0, Math.ceil((Date.parse(offer.data.expires_at) - now) / 1000))}s)</p><pre aria-label="Pairing QR">{offer.data.qr}</pre><label>Pairing URL <input readOnly value={offer.data.url} /></label><button className="btn" onClick={() => void doCopy()}>Copy</button></div> : null}
    {copy ? <p role="status">{copy}</p> : null}
  </div></PanelSection>;
}

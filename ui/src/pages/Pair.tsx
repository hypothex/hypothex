import { useEffect, useRef, useState } from 'react';
import { auth } from '../api/auth';
import { api, ApiError } from '../api/client';
import type { PairResult } from '../api/models';
import './pair.css';
interface Offer { offer_id:string;secret:string }
/** Capture before removing the fragment, retaining it through StrictMode's effect replay. */
export function parsePairFragment(fragment:string):Offer|null {
 const match=/^#(p_[a-f0-9]{12})\.([A-Za-z0-9_-]{20,256})$/.exec(fragment);
 return match ? {offer_id:match[1]!,secret:match[2]!} : null;
}
export function PairPage() {
 const captured=useRef<{offer:Offer|null}|null>(null);
 if (!captured.current) captured.current={offer:parsePairFragment(window.location.hash)};
 const [device,setDevice]=useState('Browser');
 const [pending,setPending]=useState(false);
 const busy=useRef(false);
 const active=useRef(true);
 const [error,setError]=useState<string|null>(null);
 const [result,setResult]=useState<PairResult|null>(null);
 useEffect(()=>{
  history.replaceState(history.state,'',window.location.pathname+window.location.search);
  active.current=true;
  return ()=>{active.current=false;queueMicrotask(()=>{if(!active.current && captured.current) captured.current.offer=null;});};
 },[]);
 const submit=async():Promise<void>=>{
  const offer=captured.current?.offer;
  if(!offer || busy.current || !device.trim() || device.trim().length>64) return;
  busy.current=true;setPending(true);setError(null);
  const credential=auth.capture();
  try {
   const paired=await api.pair({...offer,device:device.trim(),client:'browser'},credential);
   if(!active.current || !auth.current(credential.generation)) return;
   captured.current!.offer=null;
   auth.select(null);
   setResult(paired);
  } catch(err) {
   if(!active.current || !auth.current(credential.generation)) return;
   if(err instanceof ApiError && err.status===400) captured.current!.offer=null;
   if(!(err instanceof Error && err.name==='AbortError')) setError(err instanceof ApiError && err.status===429 ? 'Too many attempts. Try again later.' : 'Pairing failed. Check the link or request a new one with hx pair.');
  } finally { if(active.current) {busy.current=false;setPending(false);} }
 };
 return <main className="pair-page"><section className="pair-card"><h1>Hypothex</h1><p>{window.location.origin}</p>
 {result ? <><h2>Device paired</h2><p>@{result.user} · {result.scope}</p><a className="btn primary" href="/">Home</a></> : <>
 <h2>Pair this device</h2>
 {!captured.current?.offer ? <p role="alert">Invalid or missing pairing link. Run <code>hx pair</code> to create a fresh link.</p> : <form onSubmit={e=>{e.preventDefault();void submit();}}><p>Offer {captured.current.offer.offer_id.slice(0,8)}…</p><label htmlFor="pair-device">Device name</label><input id="pair-device" value={device} maxLength={64} disabled={pending} onChange={e=>setDevice(e.target.value)}/><button className="btn primary" disabled={pending || !device.trim() || device.trim().length>64}>Pair</button></form>}
 {pending && <p role="status">Pairing…</p>}{error && <p role="alert">{error}</p>}</>}
 </section></main>;
}

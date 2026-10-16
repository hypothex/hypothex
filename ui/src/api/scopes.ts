import type { Capability, Principal, Scope } from './models';
const order: Scope[] = ['read', 'launch', 'admin'];
export function isScoped(p: Capability | undefined): p is Principal { return p?.auth === 'on'; }
export function hasScope(p: Capability | undefined, scope: Scope): boolean {
  if (!p) return false;
  if (p.auth === 'legacy') return true;
  return order.indexOf(p.scope) >= order.indexOf(scope);
}
export function mayAct(p: Capability | undefined, owner: string | null | undefined): boolean {
  return hasScope(p, 'admin') || (hasScope(p, 'launch') && p?.auth === 'on' && !!owner && p.user === owner);
}
export function phase3Available(p: Capability | undefined): p is Principal { return !!p && p.auth !== 'legacy'; }

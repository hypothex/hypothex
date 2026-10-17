import type { ReactNode } from 'react';
export function ScopeHint({children, allowed, reason = 'This action needs a higher scope'}: {children:ReactNode;allowed:boolean;reason?:string}) {
 return <span title={allowed ? undefined : reason} aria-description={allowed ? undefined : reason}>{children}</span>;
}

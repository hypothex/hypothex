import { useQueryClient } from '@tanstack/react-query';
import { useEffect, type ReactNode } from 'react';
import { auth } from './auth';
import { clearSessionQueries } from './queries';
/** Remains mounted on the public pairing route as well as the authenticated shell. */
export function SessionReset({children}:{children:ReactNode}) {
 const client=useQueryClient();
 useEffect(()=>auth.onReset(()=>clearSessionQueries(client)),[client]);
 return <>{children}</>;
}

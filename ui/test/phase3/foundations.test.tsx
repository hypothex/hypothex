import {afterEach,expect,test} from 'bun:test';
import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {StrictMode} from 'react';
import {auth} from '../../src/api/auth';
import {api,ApiError} from '../../src/api/client';
import {clearSessionQueries,createQueryClient,fetchMe,queryKeys} from '../../src/api/queries';
import {keysForEvent,EventStream,type SocketLike,type Clock} from '../../src/api/events';
import {notebookEditor} from '../../src/api/notebookEditors';
import {hasScope,mayAct} from '../../src/api/scopes';
import {PairPage} from '../../src/pages/Pair';
import {isAppPath} from '../../src/pages/components/links';
import {renameEach} from '../../src/run/RunName';
import {HomePage} from '../../src/home/HomePage';
import {cleanedArtifact,cleanedMatches} from '../../src/pages/components/cleaned';
import {allFiles} from '../../src/run/files';
import {FileList} from '../../src/run/FileList';
import {RunActions} from '../../src/pages/components/RunActions';
import {CheckpointTable} from '../../src/pages/components/TrainingDetails';
import {makeDetail} from '../pages/fixtures';
import {mockApi,renderWithClient,restoreFetch} from '../pages/helpers';
import {makeHomeSummary,runningRecord} from '../home/homeFixtures';
import type {Principal,HxEvent,CleanedArtifact} from '../../src/api/models';
const alice={auth:'on',user:'alice',scope:'launch',scopes:['read','launch'],session_id:'s_test',client:'browser',public_url:null} satisfies Principal;
const realFetch=globalThis.fetch;
afterEach(()=>{cleanup();restoreFetch();globalThis.fetch=realFetch;auth.select(null);history.replaceState(null,'','/');});
function deferred<T>() {let resolve!:(v:T)=>void;const promise=new Promise<T>(r=>{resolve=r;});return {promise,resolve};}
test('scopes fail closed and owner actions never guess a legacy owner',()=>{
 for(const p of [undefined,{...alice,scope:'read' as const}]) {expect(hasScope(p,'launch')).toBe(false);expect(mayAct(p,'alice')).toBe(false);}
 expect(mayAct(alice,'alice')).toBe(true);expect(mayAct(alice,'sv')).toBe(false);expect(mayAct(alice,null)).toBe(false);
 expect(mayAct({...alice,scope:'admin'},null)).toBe(true);
 expect(hasScope({auth:'legacy',legacy:true},'launch')).toBe(true);
});
test('exact path admission excludes pair interception and malformed segment paths',()=>{
 for(const path of ['/','/hosts/','/queue','/settings','/storage/','/n/toy','/n/toy/2026-10-17/','/t/p/t/edit/view/','/r/r1','/x/a/b','/s/p/s']) expect(isAppPath(path)).toBe(true);
 for(const path of ['/pair','/pair/','/api/v1/runs','/mcp','/docs','/openapi.json','/unknown.js','/t/p/t/more','/hosts/extra','/n/p/day/more','/r/a%2Fb','/r/a%5Cb','/r/%zz']) expect(isAppPath(path)).toBe(false);
});
test('authenticated raw exports use exact comma query, cookie credentials and structured conflict errors',async()=>{
 auth.select('synthetic-bearer');const seen:{url:string;init?:RequestInit}[]=[];
 globalThis.fetch=(async(url:RequestInfo|URL,init?:RequestInit)=>{seen.push({url:String(url),init});return new Response('raw,\ntext\n');}) as unknown as typeof fetch;
 expect(await api.exportTask('p space','t',{primary:'latency/p95',format:'csv',metrics:['a/x','b/y'],groups:['g1','g2']})).toBe('raw,\ntext\n');
 expect(seen[0]!.url).toBe('/api/v1/tasks/p%20space/t/export?primary=latency%2Fp95&format=csv&metrics=a%2Fx%2Cb%2Fy&groups=g1%2Cg2');
 expect(seen[0]!.init?.credentials).toBe('same-origin');expect(new Headers(seen[0]!.init?.headers).get('Authorization')).toBe('Bearer synthetic-bearer');
 globalThis.fetch=(async()=>new Response(JSON.stringify({error:'conflict',type:'NotebookConflictError',current:{hash:'new'}}),{status:409})) as unknown as typeof fetch;
 try {await api.exportTask('p','t',{});throw new Error('expected failure');}catch(e){expect(e).toBeInstanceOf(ApiError);expect((e as ApiError).body).toEqual({error:'conflict',type:'NotebookConflictError',current:{hash:'new'}});}
});
test('a delayed raw export cannot cross credential generations',async()=>{
 const pending=deferred<Response>();auth.select('old');globalThis.fetch=(()=>pending.promise) as unknown as typeof fetch;
 const result=api.exportTask('p','t',{}).catch(e=>e);auth.select('new');pending.resolve(new Response('private old export'));
 expect((await result as Error).name).toBe('AbortError');
});
test('me404 validates root transport before granting legacy capability',async()=>{
 const calls=mockApi({'GET /api/v1/auth/me':new (await import('../pages/helpers')).HttpReply(404,{}),'GET /api/v1/projects':[]});
 expect(await fetchMe()).toEqual({auth:'legacy',legacy:true});expect(calls.map(c=>c.url)).toEqual(['/api/v1/auth/me','/api/v1/projects']);
});
test('public pairing strips fragment before POST and drops the previous bearer even under StrictMode',async()=>{
 auth.select('previous-bearer');const secret='a'.repeat(43);history.replaceState(null,'',`/pair#p_012345abcdef.${secret}`);
 let body:unknown;let header:string|null='not-called';
 globalThis.fetch=(async(url:RequestInfo|URL,init?:RequestInit)=>{expect(String(url)).toBe('/api/v1/auth/pair');expect(window.location.hash).toBe('');header=new Headers(init?.headers).get('Authorization');body=JSON.parse(String(init?.body));return new Response(JSON.stringify({user:'alice',scope:'launch',scopes:['read','launch'],session_id:'s_1'}));}) as unknown as typeof fetch;
 render(<StrictMode><PairPage/></StrictMode>);expect(window.location.hash).toBe('');expect(header).toBe('not-called');
 fireEvent.change(screen.getByLabelText('Device name'),{target:{value:'Lab browser'}});fireEvent.click(screen.getByRole('button',{name:'Pair'}));
 await screen.findByText('Device paired');expect(header).toBeNull();expect(body).toEqual({offer_id:'p_012345abcdef',secret,device:'Lab browser',client:'browser'});
 expect(auth.capture().token).toBeNull();expect(document.body.textContent).not.toContain(secret);expect(screen.getByRole('link',{name:'Home'})).toBeTruthy();
});
test('malformed pairing fragments clear immediately and never send requests',()=>{
 history.replaceState(null,'','/pair#malformed');let calls=0;globalThis.fetch=(async()=>{calls++;return new Response('{}');}) as unknown as typeof fetch;
 render(<PairPage/>);expect(window.location.hash).toBe('');expect(screen.getByRole('alert')).toBeTruthy();expect(calls).toBe(0);
});
test('renameEach stops continuation and rollback when another principal is selected',async()=>{
 auth.select('alice');const pending=deferred<unknown>();const calls:string[]=[];
 const result=renameEach([{runId:'a',previous:'old-a'},{runId:'b',previous:'old-b'},{runId:'c',previous:'old-c'}],'new',async id=>{calls.push(id);if(id==='b') return pending.promise;}).catch(e=>e);
 await waitFor(()=>expect(calls).toEqual(['a','b']));auth.select('sv');pending.resolve({});expect((await result as Error).name).toBe('AbortError');expect(calls).toEqual(['a','b']);
});
test('notebook attribution and storage events invalidate their exact families and clear on session reset',()=>{
 const event={sequence:1,run_id:null,type:'notebook.updated',project:'toy',payload:{day:'2026-10-17',author:'human:alice'},created_at:'2026-10-17T00:00:00Z'} as HxEvent;
 expect(keysForEvent(event)).toEqual([['notebook','toy']]);expect(notebookEditor('toy','2026-10-17')?.author).toBe('human:alice');
 expect(keysForEvent({...event,type:'run.artifacts_cleaned',run_id:'r'})).toContainEqual(['storage']);
 expect(keysForEvent({...event,type:'storage.applied'})).toContainEqual(['taskRuns','toy']);
 const qc=createQueryClient();clearSessionQueries(qc);expect(notebookEditor('toy','2026-10-17')).toBeUndefined();
 expect(queryKeys.export('p','t',{primary:'a/x'})).not.toEqual(queryKeys.export('p','t',{primary:'b/y'}));
});
test('Mine filters only Running now and sends the exact owner/status read',async()=>{
 const running=runningRecord({owner:'sv'});const summary=makeHomeSummary({running:[running]});const mine=runningRecord({run_id:'alice-run',owner:'alice',name:'Alice trial'});
 const calls=mockApi({'GET /api/v1/auth/me':alice,'GET /api/v1/overview':summary,'GET /api/v1/hosts':[],'GET /api/v1/runs?owner=me&status=running':[mine]});
 renderWithClient(<HomePage/>);fireEvent.click(await screen.findByRole('button',{name:'Mine'}));
 await waitFor(()=>expect(calls.some(c=>c.url==='/api/v1/runs?owner=me&status=running')).toBe(true));
 const region=screen.getByRole('region',{name:/^Running now/});await within(region).findByText('@alice');expect(within(region).queryByText('@sv')).toBeNull();expect(screen.getByRole('region',{name:/^Recent runs/})).toBeTruthy();expect(screen.getByRole('region',{name:/^Tasks/})).toBeTruthy();
});
test('cleaned markers match exact environment/path boundaries and never legacy identity',()=>{
 const marker={path:'/same/ckpt',environment_id:'host'};expect(cleanedMatches('/same/ckpt','host',marker)).toBe(true);expect(cleanedMatches('/same/ckpt/weights','host',marker)).toBe(true);
 for(const [path,env] of [['/same/ckpt','hub'],['/same/ckpt2','host']]) expect(cleanedMatches(path!,env,marker)).toBe(false);
 expect(cleanedMatches('/same/ckpt','host',{path:'/same/ckpt'})).toBe(false);expect(cleanedMatches('/same/ckpt','host',{...marker,environment_id:null})).toBe(false);
});
test('file and checkpoint surfaces retain metrics but remove existing-file copy after cleanup',()=>{
 const detail=makeDetail();const artifact=detail.record.artifacts.find(a=>a.kind==='checkpoint');expect(artifact).toBeTruthy();
 const marker={path:artifact!.path,environment_id:detail.record.environment_id,bytes:42,at:'2026-10-17T00:00:00Z',actor:'alice',plan_id:'cp-test'} satisfies CleanedArtifact;
 detail.cleaned=[marker];render(<><FileList rows={allFiles(detail)}/><CheckpointTable artifacts={detail.record.artifacts} environmentId={detail.record.environment_id} cleaned={detail.cleaned}/></>);
 expect(document.querySelectorAll('s').length).toBeGreaterThanOrEqual(2);expect(screen.getAllByText('✕ 2026-10-17 42 bytes')).toHaveLength(2);expect(screen.getByRole('table',{name:'Checkpoint metrics'})).toBeTruthy();
 const row=allFiles(detail).find(r=>r.cleaned);expect(row?.rawPath).toBe(artifact!.path);expect(allFiles(detail).find(r=>r.name==='Run folder')?.cleaned).toBeUndefined();
});
test('current WS4401 stops all retry timers; stale socket revocation cannot lock replacement',()=>{
 const timers=new Map<number,()=>void>();let next=0;
 const clock:Clock={setTimeout(fn){timers.set(++next,fn);return next;},clearTimeout(id){timers.delete(id as number);}};
 const sockets:SocketLike[]=[];
 const stream=()=>new EventStream({url:'ws://127.0.0.1/api/v1/ws',ticket:null,clock,onEvents:()=>{},createSocket:()=>{const socket:SocketLike={readyState:1,onopen:null,onmessage:null,onclose:null,onerror:null,send(){},close(){}};sockets.push(socket);return socket;}});
 auth.accept(auth.select('alice'));const first=stream();first.start();const stale=sockets[0]!.onclose!;auth.accept(auth.select('sv'));stale(new CloseEvent('close',{code:4401}));expect(auth.snapshot().status).toBe('unlocked');first.stop();
 const current=stream();current.start();sockets.at(-1)!.onclose!(new CloseEvent('close',{code:4401}));expect(auth.snapshot().status).toBe('locked');const count=sockets.length;for(let i=0;i<5;i++) {for(const fn of [...timers.values()]) fn();}expect(sockets).toHaveLength(count);expect(timers.size).toBe(0);current.stop();
});

test('Re-infer disables a known cleaned checkpoint while retaining historical scores',async()=>{
 const detail=makeDetail();const checkpoint=detail.record.artifacts.filter(a=>a.kind==='checkpoint').at(-1)!;
 mockApi({});renderWithClient(<RunActions record={detail.record} served inferStage cleaned={[{path:checkpoint.path,environment_id:detail.record.environment_id,bytes:42,at:'2026-10-17T00:00:00Z',actor:'alice',plan_id:'cp-test'}]}/>);
 fireEvent.click(screen.getByRole('button',{name:'More actions'}));const action=screen.getByRole('menuitem',{name:'Re-infer'});expect((action as HTMLButtonElement).disabled).toBe(true);expect(action.title).toBe('Checkpoint was deleted by cleanup');
});

test('same-path source and pulled file rows only lose controls for the deleted environment',()=>{
 const marker={path:'/same/checkpoint',environment_id:'hub',bytes:9,at:'2026-10-17',actor:'sv',plan_id:'cp'};
 render(<FileList rows={['source','hub'].map(environmentId=>({name:environmentId,path:'/same/checkpoint',rawPath:'/same/checkpoint',environmentId,copy:`${environmentId}:/same/checkpoint`,icon:'box',size:9,href:'/r/test?tab=files',cleaned:cleanedArtifact('/same/checkpoint',environmentId,[marker])}))}/>);
 expect(document.querySelectorAll('s')).toHaveLength(1);expect(screen.getByRole('link',{name:'source'})).toBeTruthy();expect(screen.queryByRole('link',{name:'hub'})).toBeNull();expect(screen.getAllByRole('button')).toHaveLength(1);
});

test('run header reconnect stays disabled when the host requires credential repair',()=>{
 const detail=makeDetail();mockApi({});renderWithClient(<RunActions record={detail.record} phase="stale" served hostName="shared" hostRepair="auth failed: hx hosts pair shared <pairing-url>"/>);const button=screen.getByRole('button',{name:'Reconnect'});expect((button as HTMLButtonElement).disabled).toBe(true);expect(button.title).toContain('hx hosts pair shared');
});

test('pair device name enforces the API 64-character boundary before redemption',async()=>{
 history.replaceState(null,'','/pair#p_012345abcdef.'+'a'.repeat(43));const sent:string[]=[];globalThis.fetch=(async(_url:RequestInfo|URL,init?:RequestInit)=>{sent.push(JSON.parse(String(init?.body)).device);return new Response(JSON.stringify({user:'alice',scope:'launch',scopes:['read','launch'],session_id:'s_1'}));}) as unknown as typeof fetch;
 render(<PairPage/>);const input=screen.getByLabelText('Device name') as HTMLInputElement;expect(input.maxLength).toBe(64);fireEvent.change(input,{target:{value:'a'.repeat(65)}});expect((screen.getByRole('button',{name:'Pair'}) as HTMLButtonElement).disabled).toBe(true);fireEvent.submit(input.closest('form')!);expect(sent).toHaveLength(0);
 fireEvent.change(input,{target:{value:'a'.repeat(64)}});fireEvent.click(screen.getByRole('button',{name:'Pair'}));await screen.findByText('Device paired');expect(sent).toEqual(['a'.repeat(64)]);
});

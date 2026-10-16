import { existsSync, readFileSync } from 'node:fs';
import { resolve, relative } from 'node:path';
import type { APIRequestContext, BrowserContext } from '@playwright/test';
import { test, expect, getJson, OWN_HUBS, expectTheme } from './fixtures';
import { TEAM_DEMO_FILE, TEAM_DARK_DEMO_FILE } from './paths';
import type { CleanPlan,CleanResult,NotebookDay,PairingOffer,PairResult,RunDetail,StorageReport,TaskRuns } from '../src/api/models';

test.use({expectedResourceStatuses:[409]});

/** Each theme has its own disposable team home: writes never race the other theme. */
test('team screens, cookie pairing, notebook conflicts, exports, exact cleanup and revocation',async({page,request,browser,baseURL,theme},testInfo)=>{
 test.setTimeout(180000);page.setDefaultTimeout(10000);
 const own=OWN_HUBS[baseURL!];if(!own) throw new Error('No isolated team home');
 const mapping=JSON.parse(readFileSync(theme==='dark'?TEAM_DARK_DEMO_FILE:TEAM_DEMO_FILE,'utf8')) as Record<string,unknown>;
 const generic=mapping.generic;if(typeof generic!=='string'||!generic.includes('/')) throw new Error('Generic demo missing');
 const [project,task]=generic.split('/') as [string,string];const taskPath=`/t/${encodeURIComponent(project)}/${encodeURIComponent(task)}`;
 const team=mapping.team as {storage_runs?:string[]};expect(team.storage_runs?.includes('st-a')).toBe(true);
 await page.context().grantPermissions(['clipboard-read','clipboard-write'],{origin:baseURL!});
 await expectTheme(page,theme);
 await expect(page.getByRole('navigation',{name:'Navigation',exact:true})).toBeVisible();
 for(const name of [/^Running now/,/^Tasks/,/^Recent runs/]) await expect(page.getByRole('heading',{name})).toBeVisible();
 await page.goto('/settings');await expect(page.getByRole('heading',{level:1,name:'Settings'})).toBeVisible();
 for(const name of ['Sessions','Users','Add device','Notifications']) await expect(page.getByRole('region',{name,exact:true})).toBeVisible();
 await expect(page.getByText('Current session',{exact:false})).toBeVisible();
 await page.screenshot({path:testInfo.outputPath(`settings-${theme}.png`),fullPage:true});
 await page.locator('.phase3-page').screenshot({path:testInfo.outputPath(`settings-content-${theme}.png`)});
 for(const channel of ['Slack','email']) {const response=page.waitForResponse(r=>r.url().endsWith('/api/v1/notify/test'));await page.getByRole('button',{name:`Test ${channel}`,exact:true}).click();expect((await (await response).json()).ok).toBe(true);}
 const offerSection=page.getByRole('region',{name:'Add device',exact:true});const uiOfferReply=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/auth/pairings'));await offerSection.getByRole('button',{name:'Create pairing link'}).click();const uiOffer=await uiOfferReply;expect(uiOffer.ok()).toBe(true);const boundedOffer=await uiOffer.json() as PairingOffer;expect(Date.parse(boundedOffer.expires_at)-Date.now()).toBeLessThanOrEqual(300000);expect((await offerSection.getByRole('textbox',{name:'Pairing URL'}).inputValue())===boundedOffer.url).toBe(true);
 const taskRuns=await getJson<TaskRuns>(request,`/api/v1/tasks/${project}/${task}/runs`);
 await page.goto(taskPath);await expect(page.getByRole('heading',{level:1,name:task,exact:true})).toBeVisible();
 await expect(page.getByRole('tablist',{name:'Task',exact:true})).toBeVisible();await expect(page.getByRole('complementary',{name:'Runs',exact:true})).toBeVisible();
 await expect(page.getByRole('table',{name:'Paper baselines',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Export',exact:true}).click();const exportDialog=page.getByRole('dialog',{name:'Export',exact:true});
 for(const format of ['latex','markdown','csv']) {
  await exportDialog.getByRole('combobox',{name:'Format',exact:true}).selectOption(format);await expect(exportDialog.getByRole('button',{name:'Download',exact:true})).toBeEnabled();
  const expected=await request.get(`/api/v1/tasks/${project}/${task}/export`,{params:{primary:taskRuns.primary,format,noise:'both',digits:'3'}});expect(expected.ok()).toBe(true);
  await exportDialog.getByRole('button',{name:'Copy',exact:true}).click();expect(await page.evaluate(()=>navigator.clipboard.readText())).toBe(await expected.text());
  const download=page.waitForEvent('download');await exportDialog.getByRole('button',{name:'Download',exact:true}).click();const file=await (await download).path();expect(file).not.toBeNull();expect(readFileSync(file!,'utf8')).toBe(await expected.text());
 }
 await page.keyboard.press('Escape');
 const [trainingProject,trainingTask]=String(mapping.training).split('/') as [string,string];
 const trainingRuns=await getJson<TaskRuns>(request,`/api/v1/tasks/${trainingProject}/${trainingTask}/runs`);const alternate=trainingRuns.score_keys.find(key=>key!==trainingRuns.primary);if(!alternate) throw new Error('Training needs alternate recorded metric');
 const saved=await request.put(`/api/v1/tasks/${trainingProject}/${trainingTask}/views/team-export`,{data:{text:'title: Team export\npanels:\n  - type: leaderboard\n    title: Rankings\n',command_id:crypto.randomUUID()}});expect(saved.ok()).toBe(true);
 await page.goto(`/t/${trainingProject}/${trainingTask}?tab=view:team-export`);await page.getByLabel('Metric',{exact:true}).selectOption(alternate);await expect(page.getByRole('button',{name:'Export',exact:true})).toBeEnabled();
 const exportResponse=page.waitForResponse(r=>r.url().includes('/export?')&&new URL(r.url()).searchParams.get('primary')===alternate);await page.getByRole('button',{name:'Export',exact:true}).click();expect((await exportResponse).ok()).toBe(true);await expect(page.getByRole('dialog',{name:'Export',exact:true}).getByRole('button',{name:'Download',exact:true})).toBeEnabled();await page.keyboard.press('Escape');
 await page.goto(`/n/${encodeURIComponent(project)}`);const today=await getJson<NotebookDay>(request,`/api/v1/projects/${project}/notebook/today`);
 await expect(page.getByRole('heading',{level:2,name:today.day,exact:true})).toBeVisible();
 const marker=`Browser ${theme} [[run:st-b]] [[run:missing-e2e]]`;
 await page.getByRole('textbox',{name:'New entry',exact:true}).fill(marker);const append=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().includes('/notebook/'));await page.getByRole('button',{name:'Add entry',exact:true}).click();expect((await append).ok()).toBe(true);
 await expect(page.getByRole('textbox',{name:'New entry',exact:true})).toHaveValue('');
 await expect(page.locator('a[href="/r/st-b"]').first()).toBeVisible();await expect(page.locator('[aria-disabled="true"]').filter({hasText:'missing-e2e'})).toBeVisible();
 await page.getByRole('button',{name:'Edit day',exact:true}).click();const text=page.getByRole('textbox',{name:'Day text',exact:true});const mine=(await text.inputValue())+`\nMine ${theme}\n`;await text.fill(mine);
 const other=await request.post(`/api/v1/projects/${project}/notebook/${today.day}`,{data:{text:`Concurrent ${theme}`,command_id:crypto.randomUUID()}});expect(other.ok()).toBe(true);
 await page.getByRole('button',{name:'Save',exact:true}).click();await expect(page.getByRole('alert',{name:'Notebook conflict'})).toBeVisible();await expect(page.getByRole('region',{name:'Mine',exact:true})).toContainText(`Mine ${theme}`);
 await page.getByRole('button',{name:'Keep mine',exact:true}).click();await expect(page.getByRole('textbox',{name:'Day text',exact:true})).toHaveCount(0);expect((await getJson<NotebookDay>(request,`/api/v1/projects/${project}/notebook/${today.day}`)).text).toBe(mine);
 await page.screenshot({path:testInfo.outputPath(`notebook-${theme}.png`),fullPage:true});
 await page.goto('/storage');await expect(page.getByRole('heading',{level:1,name:'Storage',exact:true})).toBeVisible();
 const report=await getJson<StorageReport>(request,'/api/v1/storage');expect(report.total_bytes).toBeGreaterThan(0);
 for(const name of ['By project','By host','Largest']) await expect(page.getByRole('region',{name,exact:true})).toBeVisible();
 const dry=page.waitForResponse(r=>r.url().endsWith('/api/v1/storage/plan')&&r.request().method()==='POST');await page.getByRole('button',{name:'Dry run',exact:true}).click();const plan=await (await dry).json() as CleanPlan;expect(plan.items.length).toBeGreaterThan(0);
 const localItems=plan.items.filter(i=>i.run_id==='st-a'||i.run_id==='st-b');expect(localItems.length).toBe(2);
 for(const item of localItems) {const rel=relative(resolve(own.home),resolve(item.path));expect(rel.startsWith('..')).toBe(false);expect(existsSync(item.path)).toBe(true);}
 const protectedItem=report.items.find(i=>i.run_id==='st-star'&&i.kind==='artifact');expect(protectedItem).toBeTruthy();
 const sharedInput=report.items.find(i=>i.run_id==='st-parent'&&i.kind==='artifact');expect(sharedInput).toBeTruthy();
 const preservedPaths=[protectedItem!.path,sharedInput!.path,...['st-a','st-b'].map(id=>resolve(own.home,'store',project,'runs',id,'run.yaml'))];const preservedBytes=preservedPaths.map(path=>readFileSync(path));
 await page.getByRole('button',{name:'Apply',exact:true}).click();const dialog=page.getByRole('dialog',{name:'Apply cleanup',exact:true});await dialog.getByLabel('Confirm bytes',{exact:true}).fill(String(plan.total_bytes-1));await expect(dialog.getByRole('button',{name:'Apply',exact:true})).toBeDisabled();
 await dialog.getByLabel('Confirm bytes',{exact:true}).fill(String(plan.total_bytes));const applied=page.waitForResponse(r=>r.url().endsWith(`/storage/plans/${plan.plan_id}/apply`));await dialog.getByRole('button',{name:'Apply',exact:true}).click();const result=await (await applied).json() as CleanResult;
 await expect(page.getByRole('region',{name:'Cleanup result',exact:true})).toContainText(String(result.freed_bytes));expect(result.freed_bytes).toBe(result.deleted.reduce((sum,i)=>sum+i.bytes,0));
 for(const item of localItems) expect(existsSync(item.path)).toBe(false);for(const [index,path] of preservedPaths.entries()) {expect(existsSync(path)).toBe(true);expect(readFileSync(path).equals(preservedBytes[index]!)).toBe(true);}
 await expect(page.getByRole('button',{name:'Dry run',exact:true})).toBeEnabled();
 await page.screenshot({path:testInfo.outputPath(`storage-${theme}.png`),fullPage:true});
 const cleaned=await getJson<RunDetail>(request,'/api/v1/runs/st-a');expect(cleaned.cleaned?.length).toBeGreaterThan(0);
 await page.goto('/r/st-a');const archivedRuns=await getJson<TaskRuns>(request,`/api/v1/tasks/${project}/${task}/runs?archived=true`);const row=archivedRuns.runs.find(r=>r.run_id==='st-a');if(!row) throw new Error('Archived fixture missing');
 await expect(page.getByRole('heading',{level:1})).toContainText(row.renamed?row.name:`${row.derived_name}${row.seed==null?'':` · seed ${row.seed}`}`);await expect(page.getByRole('tablist',{name:'Run',exact:true})).toBeVisible();await expect(page.locator('s').first()).toBeVisible();
 await page.getByRole('tab',{name:'Files',exact:true}).click();await expect(page.locator('s').first()).toBeVisible();
 await page.goto('/hosts');await expect(page.getByRole('heading',{name:'Hosts',level:1})).toBeVisible();await page.goto('/queue');await expect(page.getByRole('heading',{name:'Queue',level:1})).toBeVisible();
 // Public redemption uses a clean context without owner storage or Authorization.
 const paired=await browser.newContext({baseURL,colorScheme:theme});
 try {
  await paired.addInitScript(value=>localStorage.setItem('hx-theme',value),theme);
  const pairPage=await paired.newPage();const seen:string[]=[];pairPage.on('request',r=>{if(new URL(r.url()).pathname.startsWith('/api/')) seen.push(new URL(r.url()).pathname);});
  const offer=await request.post('/api/v1/auth/pairings',{data:{user:'alice',scope:'launch',ttl_seconds:300}});expect(offer.ok()).toBe(true);const offerBody=await offer.json() as PairingOffer;
  const fragment=new URL(offerBody.url).hash;
  await paired.addInitScript(hash=>{if(location.pathname==='/pair'&&!sessionStorage.getItem('e2e-fragment-used')){history.replaceState(null,'','/pair'+hash);sessionStorage.setItem('e2e-fragment-used','1');}},fragment);
  await pairPage.goto('/pair');await expect(pairPage.getByLabel('Device name')).toBeVisible();expect(await pairPage.evaluate(()=>location.hash)).toBe('');expect(seen).toEqual([]);await expect(pairPage.getByRole('navigation',{name:'Navigation'})).toHaveCount(0);
  await pairPage.getByLabel('Device name').fill(`Alice ${theme}`);const redemption=pairPage.waitForResponse(r=>r.url().endsWith('/auth/pair'));await pairPage.getByRole('button',{name:'Pair',exact:true}).click();const identity=await (await redemption).json() as PairResult;expect(identity.user).toBe('alice');expect('token' in identity).toBe(false);const [offerId,offerSecret]=fragment.slice(1).split('.');expect((await paired.request.post('/api/v1/auth/pair',{data:{offer_id:offerId,secret:offerSecret,device:'reused',client:'browser'}})).status()).toBe(400);
  const cookieMe=await paired.request.get('/api/v1/auth/me');expect((await cookieMe.json()).user).toBe('alice');await pairPage.getByRole('link',{name:'Home',exact:true}).click();await expect(pairPage.getByRole('button',{name:'Mine',exact:true})).toBeVisible();
  seen.length=0;await pairPage.goto('/settings');await expect(pairPage.getByRole('region',{name:'Sessions',exact:true})).toBeVisible();await expect(pairPage.getByRole('region',{name:'Users',exact:true})).toHaveCount(0);await expect(pairPage.getByRole('region',{name:'Notifications',exact:true})).toHaveCount(0);expect(seen.includes('/api/v1/auth/users')).toBe(false);expect(seen.includes('/api/v1/notify')).toBe(false);
  expect((await paired.request.get('/api/v1/storage')).status()).toBe(403);expect((await paired.request.get('/api/v1/auth/me')).status()).toBe(200);
  await pairPage.goto('/storage');await expect(pairPage.getByText('Storage requires admin scope.')).toBeVisible();expect(seen.includes('/api/v1/storage')).toBe(false);
  await pairPage.goto(taskPath);await pairPage.getByRole('button',{name:'New run',exact:true}).click();const launch=pairPage.getByRole('dialog',{name:/New run/});await expect(launch).toBeVisible();
  await expect(launch.getByRole('radio',{name:'local',exact:true})).toBeDisabled();await launch.getByRole('radio',{name:/^shared\b/}).check();const gpuCount=launch.getByLabel('GPUs per run',{exact:true});while(Number(await gpuCount.textContent())>0) await launch.getByRole('button',{name:'Fewer GPUs per run'}).click();
  await launch.getByLabel('Seeds',{exact:true}).fill('99');await launch.getByLabel('Command',{exact:true}).fill('sh -c "echo team {seed}; sleep 20"');const hypothesis=`Team Alice ${theme}`;await launch.getByLabel('Hypothesis',{exact:true}).fill(hypothesis);const launchReply=pairPage.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/hosts/shared/runs'));await launch.getByRole('button',{name:/^Launch/}).click();const launchedResponse=await launchReply;expect(launchedResponse.status(),await launchedResponse.text()).toBe(200);const launchRecord=await launchedResponse.json() as RunDetail['record'];expect(launchRecord.owner).toBe('alice');
  let launched:RunDetail['record']|undefined;await expect.poll(async()=>{const runs=await getJson<RunDetail['record'][]>(request,`/api/v1/runs?project=${project}&limit=500`);launched=runs.find(r=>r.hypothesis===hypothesis);return launched?.owner;},{timeout:30000}).toBe('alice');expect(launched!.created_by).toBe('human:alice');
  await pairPage.goto(`/r/${launched!.run_id}`);await pairPage.getByRole('button',{name:'More actions'}).click();await expect(pairPage.getByRole('menuitem',{name:'Stop',exact:true})).toBeEnabled();await pairPage.getByRole('menuitem',{name:'Stop',exact:true}).click();await pairPage.getByRole('menuitem',{name:'Stop ✓?',exact:true}).click();
  await pairPage.goto('/r/st-b');await pairPage.getByRole('button',{name:'More actions'}).click();await expect(pairPage.getByRole('menuitem',{name:'Unarchive',exact:true})).toBeEnabled();
  await pairPage.goto('/r/st-a');await pairPage.getByRole('button',{name:'More actions'}).click();await expect(pairPage.getByRole('menuitem',{name:'Unarchive',exact:true})).toBeDisabled();
  const revoked=await request.post(`/api/v1/auth/sessions/${identity.session_id}/revoke`,{data:{command_id:crypto.randomUUID()}});expect(revoked.ok()).toBe(true);await pairPage.goto('/settings');await expect(pairPage.getByLabel('Token',{exact:true})).toBeVisible();const ticketCount=seen.filter(p=>p.endsWith('/ws-ticket')).length;
  await pairPage.waitForTimeout(8500);expect(seen.filter(p=>p.endsWith('/ws-ticket')).length).toBe(ticketCount);
  const fresh=await request.post('/api/v1/auth/pairings',{data:{user:'alice',scope:'read',ttl_seconds:300}});expect(fresh.ok()).toBe(true);const freshFragment=new URL((await fresh.json() as PairingOffer).url).hash;
  await paired.addInitScript(hash=>{if(location.pathname==='/pair'&&!sessionStorage.getItem('e2e-fresh-used')){history.replaceState(null,'','/pair'+hash);sessionStorage.setItem('e2e-fresh-used','1');}},freshFragment);
  await pairPage.goto('/pair');await pairPage.getByLabel('Device name').fill('Alice reader');await pairPage.getByRole('button',{name:'Pair',exact:true}).click();await pairPage.getByRole('link',{name:'Home',exact:true}).click();await expect(pairPage.getByRole('button',{name:'New run',exact:true})).toBeDisabled();
  await pairPage.goto(`/n/${project}`);await expect(pairPage.getByRole('button',{name:'Edit day',exact:true})).toBeDisabled();await expect(pairPage.getByRole('textbox',{name:'New entry',exact:true})).toBeDisabled();expect((await paired.request.get('/api/v1/auth/me')).status()).toBe(200);

 } finally {await paired.close();}
});

export interface NotebookEditor { project:string; day:string; author?:string; at:string }
const editors = new Map<string, NotebookEditor>();
const listeners = new Set<() => void>();
export function noteNotebookEditor(value: NotebookEditor): void {
 if (!value.project || !/^\d{4}-\d{2}-\d{2}$/.test(value.day) || !value.at) return;
 const key = JSON.stringify([value.project,value.day]);
 editors.delete(key); editors.set(key,value);
 if (editors.size > 256) editors.delete(editors.keys().next().value!);
 listeners.forEach(fn=>fn());
}
export function notebookEditor(project:string,day:string): NotebookEditor | undefined { return editors.get(JSON.stringify([project,day])); }
export function clearNotebookEditors(): void { editors.clear(); listeners.forEach(fn=>fn()); }
export function subscribeNotebookEditors(fn:()=>void):()=>void { listeners.add(fn); return ()=>{listeners.delete(fn);}; }

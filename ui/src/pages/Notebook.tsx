import { useParams } from "@tanstack/react-router";
import { useSyncExternalStore } from "react";
import { auth } from "../api/auth";
import { useMe, useNotebookDay, useNotebookDays } from "../api/queries";
import { AppLink } from "./components/links";
import { DayView } from "./notebook/DayView";
import { withToday } from "./notebook/model";
import "./settings/settings.css";
import "./notebook/notebook.css";
export function NotebookPage() {
  const params = useParams({ strict: false }) as { project?: string; day?: string };
  return <NotebookProject project={params.project ?? ""} selectedDay={params.day} />;
}
export function NotebookProject({ project, selectedDay }: { project: string; selectedDay?: string }) {
  const me = useMe(); const p = me.data; const generation = useSyncExternalStore(auth.subscribe, auth.snapshot).generation;
  const permitted = !!p && p.auth !== "legacy" && !me.error;
  const validDay = !selectedDay || /^\d{4}-\d{2}-\d{2}$/.test(selectedDay);
  const days = useNotebookDays(project, { enabled: permitted && validDay && !!project });
  const today = useNotebookDay(project, "today", { enabled: permitted && validDay && !!project });
  const selected = useNotebookDay(project, selectedDay ?? "today", { enabled: permitted && validDay && !!project });
  const list = today.data ? withToday(days.data ?? [], { day: today.data.day, entries: 0, bytes: 0 }) : days.data ?? [];
  return <div className="phase3-page"><h1>{project} Notebook</h1>{!validDay ? <p role="alert">Invalid day; use YYYY-MM-DD.</p> : me.isPending ? <p role="status">Loading permissions…</p> : me.error ? <p role="alert">{me.error.message}</p> : !permitted ? <p>Notebook is unavailable on this hub.</p> : <div className="notebook-layout">
    <nav aria-label="Notebook days">{days.error ? <p role="alert">{days.error.message}</p> : list.map((day) => <AppLink key={day.day} href={`/n/${encodeURIComponent(project)}/${encodeURIComponent(day.day)}`} aria-current={selected.data?.day === day.day ? "page" : undefined}>{day.day} · {day.entries}</AppLink>)}</nav>
    {selected.isPending ? <p role="status">Loading notebook…</p> : selected.error ? <p role="alert">{selected.error.message}</p> : selected.data ? <DayView key={`${generation}:${project}:${selected.data.day}`} day={selected.data} writable={!!p && "scope" in p && (p.scope === "admin" || p.scope === "launch")} /> : null}
  </div>}</div>;
}

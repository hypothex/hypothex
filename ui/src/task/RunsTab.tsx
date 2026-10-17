/**
 * Runs tab (spec 4.2 "Runs"): the full table with a sticky header. Columns: select,
 * swatch, name, status (counts per state for configs), each varying param, primary mean ±
 * sd, 95% CI, Δ best (muted inside the best interval), launcher, host, GPU-h, started,
 * commit, tags. Configs expand to their seeds; headers sort; a column chooser; bulk
 * actions on the selection: Compare, Tag, Archive, Rename (checked like `RunName`, one
 * config or run at a time). Filter and grouping share the sidebar's URL state.
 */
import { type MouseEvent, type ReactElement, type ReactNode, useEffect, useRef, useState } from "react";
import { auth } from "../api/auth";
import { hasScope, mayAct } from "../api/scopes";
import { api } from "../api/client";
import type { TaskGroup, TaskRun, TaskRuns } from "../api/models";
import { RUN_EVENT_INVALIDATES, useMe, useRenameRun } from "../api/queries";
import { EmptyState } from "../chrome/EmptyState";
import { FilterField } from "../chrome/FilterField";
import { Icon } from "../chrome/Icon";
import { menuArrowKeys, useMenuFocus } from "../chrome/menuFocus";
import { Launcher } from "../chrome/Launcher";
import { Segmented } from "../chrome/Segmented";
import { StatusIcon } from "../chrome/StatusIcon";
import { colorFor } from "../lib/color";
import { fmtDate, fmtDelta, fmtInterval, fmtScore, shortId } from "../pages/components/format";
import { hrefs, isPlainClick } from "../pages/components/links";
import { ErrorBox } from "../pages/components/QueryState";
import { fmtGpuHours } from "../pages/components/SweepModel";
import { useAction } from "../pages/components/useAction";
import { nameProblem, nameToSend, renameEach, toRenameTarget } from "../run/RunName";
import {
  type Cells,
  type RunsColumn,
  type TableSortDir,
  identityCells,
  loadHiddenColumns,
  runCells,
  runsColumns,
  saveHiddenColumns,
  sortItems,
} from "./runsTable";
import { type Identity, type Selection, identities, latestRun, listIdentities } from "./useRunSelection";

export interface RunsTabProps {
  project: string;
  task: string;
  data: TaskRuns;
  selection: Selection;
  onSelection: (patch: Partial<Selection>) => void;
  onOpenCharts: () => void;
  onOpenRun: (runId: string) => void;
}

const GROUPS = [
  ["config", "By config"],
  ["run", "Each run"],
] as const;

export function RunsTab({ project, task, data, selection, onSelection, onOpenCharts, onOpenRun }: RunsTabProps): ReactElement {
  const me=useMe();
  const writable=hasScope(me.data,"launch");
  const listed = listIdentities(selection, data);
  const visible = listed.filter((i) => !i.hidden).map((i) => i.id);
  const columns = runsColumns(data);
  const [hiddenCols, setHiddenCols] = useState<string[]>(() => loadHiddenColumns(project, task));
  const shown = columns.filter((c) => !hiddenCols.includes(c.id));
  const [sort, setSort] = useState<{ col: string; dir: TableSortDir } | null>(null);
  const rows = sortItems(listed, data, sort?.col ?? null, sort?.dir ?? "desc");
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set());
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [form, setForm] = useState<"tag" | "rename" | null>(null);
  const [text, setText] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const chosen = rows.filter((i) => picked.has(i.id));
  const runIds = chosen.flatMap((i) => i.runs.map((r) => r.run_id));
  const tag = useAction({
    send: async ({ ids, tag: name }: { ids: string[]; tag: string }, opts) => {
      for (const id of ids) await api.tagRun(id, { add: [name] }, { ...opts, command_id: `${opts.command_id}:${id}` });
    },
    invalidate: RUN_EVENT_INVALIDATES,
    onSuccess: () => {
      setForm(null);
      setText("");
    },
  });
  const archive = useAction({
    send: async (ids: string[], opts) => {
      for (const id of ids) await api.archiveRun(id, true, { ...opts, command_id: `${opts.command_id}:${id}` });
    },
    invalidate: RUN_EVENT_INVALIDATES,
    onSuccess: () => setPicked(new Set()),
  });
  const rename = useRenameRun();
  const toggle = (set: ReadonlySet<string>, id: string): Set<string> => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  };
  const sortBy = (col: string): void =>
    setSort((s) => (s && s.col === col ? { col, dir: s.dir === "desc" ? "asc" : "desc" } : { col, dir: "desc" }));
  const compare = (): void => {
    const keep = new Set(chosen.map((i) => i.id));
    onSelection({ hidden: identities(data, selection.group).map((i) => i.id).filter((id) => !keep.has(id)) });
    onOpenCharts();
  };
  const saveName = async (): Promise<void> => {
    const credential=auth.capture();
    if(!writable) return;
    const item = chosen[0];
    if (!item) return;
    const problem = nameProblem(text);
    if (problem) {
      setRenameError(problem);
      return;
    }
    // typing the derived name back (or nothing) resets the name
    const renamed = item.runs.some((r) => r.renamed);
    const derived = renamed ? (latestRun(item.runs)?.derived_name ?? item.baseName) : item.baseName;
    const name = nameToSend(text, derived);
    setRenameError(null);
    if (name === null ? !renamed : renamed && name === item.baseName) {
      setForm(null);
      return;
    }
    try {
      // all or none: a refusal puts the runs already renamed back
      await renameEach(item.runs.map(toRenameTarget), name, (runId, to) => rename.mutateAsync({ runId, name: to, credential }));
      if(auth.current(credential.generation)) setForm(null);
    } catch (err) {
      if(!auth.current(credential.generation)) return;
      setRenameError(err instanceof Error ? err.message : String(err));
    }
  };
  const allPicked = rows.length > 0 && rows.every((i) => picked.has(i.id));
  return (
    <div className="runs-tab">
      <div className="ptools">
        <FilterField
          value={selection.filter}
          onChange={(filter) => onSelection({ filter })}
          placeholder="Filter  lr=3e-4 · tag:final · status:running"
          label="Filter runs"
        />
        <Segmented label="Group" options={GROUPS} value={selection.group} onChange={(group) => onSelection({ group })} />
        <ColumnChooser
          columns={columns}
          hidden={hiddenCols}
          onChange={(next) => {
            setHiddenCols(next);
            saveHiddenColumns(project, task, next);
          }}
        />
        <span className="sp" />
        <span className="muted">{`${chosen.length} selected`}</span>
        <button type="button" className="btn sm" disabled={chosen.length === 0} onClick={compare}>
          Compare
        </button>
        <button
          type="button"
          className="btn sm"
          disabled={chosen.length === 0}
          aria-expanded={form === "tag"}
          onClick={() => {
            setText("");
            setForm((f) => (f === "tag" ? null : "tag"));
          }}
        >
          Tag
        </button>
        <button type="button" className="btn sm" disabled={!chosen.every(i=>i.runs.every(r=>mayAct(me.data,r.owner))) || chosen.length === 0 || archive.pending} onClick={() => archive.run(runIds)}>
          Archive
        </button>
        <button
          type="button"
          className="btn sm"
          disabled={!writable || chosen.length !== 1}
          title={chosen.length > 1 ? "Rename one config or run at a time" : undefined}
          onClick={() => {
            setText(chosen[0]?.baseName ?? "");
            setRenameError(null);
            setForm("rename");
          }}
        >
          Rename
        </button>
      </div>
      {form === "tag" && runIds.length > 0 ? (
        <form
          className="bulk-form"
          aria-label="Tag runs"
          onSubmit={(e) => {
            e.preventDefault();
            const name = text.trim();
            if (name && runIds.length) tag.run({ ids: runIds, tag: name });
          }}
        >
          <input aria-label="Tag" value={text} placeholder="tag" onChange={(e) => setText(e.target.value)} />
          <button type="submit" className="btn sm primary" disabled={!writable || !text.trim() || tag.pending}>
            {`Add to ${runIds.length} run${runIds.length === 1 ? "" : "s"}`}
          </button>
        </form>
      ) : null}
      {form === "rename" && chosen.length === 1 ? (
        <form
          className="bulk-form"
          aria-label="Rename"
          onSubmit={(e) => {
            e.preventDefault();
            void saveName();
          }}
        >
          <input aria-label="Name" value={text} onChange={(e) => setText(e.target.value)} />
          <button type="submit" className="btn sm primary" disabled={rename.isPending}>
            Save name
          </button>
          {renameError ? <span role="alert">{renameError}</span> : null}
        </form>
      ) : null}
      {tag.error ? <ErrorBox error={tag.error} /> : null}
      {archive.error ? <ErrorBox error={archive.error} /> : null}
      {data.runs.length === 0 ? (
        <EmptyState title="No runs yet" />
      ) : (
        <div className="tblwrap runs-table">
          <table className="t" aria-label="Runs">
            <thead>
              <tr>
                <th className="sel">
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    checked={allPicked}
                    onChange={(e) => setPicked(e.target.checked ? new Set(rows.map((i) => i.id)) : new Set())}
                  />
                </th>
                <th aria-label="Colour" />
                <SortHeader col="name" label="Name" numeric={false} sort={sort} onSort={sortBy} />
                {shown.map((c) => (
                  <SortHeader key={c.id} col={c.id} label={c.label} numeric={c.numeric} sort={sort} onSort={sortBy} />
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <ItemRows
                  key={item.id}
                  item={item}
                  data={data}
                  shown={shown}
                  color={item.hidden ? undefined : colorFor(item.id, visible)}
                  picked={picked.has(item.id)}
                  onPick={() => setPicked((s) => toggle(s, item.id))}
                  expanded={open.has(item.id)}
                  onExpand={() => setOpen((s) => toggle(s, item.id))}
                  onOpenRun={onOpenRun}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface ItemRowsProps {
  item: Identity;
  data: TaskRuns;
  shown: readonly RunsColumn[];
  color: string | undefined;
  picked: boolean;
  onPick: () => void;
  expanded: boolean;
  onExpand: () => void;
  onOpenRun: (runId: string) => void;
}

/** A config or run row, and a config's seed rows while it is expanded. */
function ItemRows({ item, data, shown, color, picked, onPick, expanded, onExpand, onOpenRun }: ItemRowsProps): ReactElement {
  const cells = identityCells(item, data);
  const isGroup = item.kind === "group";
  return (
    <>
      <tr className={`${isGroup ? "g" : ""}${item.hidden ? " off" : ""}`}>
        <td className="sel">
          <input type="checkbox" aria-label={`Select ${item.name}`} checked={picked} onChange={onPick} />
        </td>
        <td>
          <span className="sw" style={color ? { background: color } : undefined} aria-hidden="true" />
        </td>
        <td className="name">
          {isGroup ? (
            <button
              type="button"
              className="caret"
              aria-expanded={expanded}
              aria-label={`${expanded ? "Collapse" : "Expand"} ${item.name}`}
              onClick={onExpand}
            >
              ▸
            </button>
          ) : null}
          <RunLink run={latestRun(item.runs)} onOpen={onOpenRun}>
            {item.name}
          </RunLink>
          {isGroup ? <span className="muted">{` ${item.runs.length} seed${item.runs.length === 1 ? "" : "s"}`}</span> : null}
        </td>
        {shown.map((c) => (
          <CellView key={c.id} col={c} cells={cells} best={isGroup && item.group?.is_best === true} asRun={!isGroup} />
        ))}
      </tr>
      {isGroup && expanded
        ? item.runs.map((run) => <SeedRow key={run.run_id} run={run} group={item.group} data={data} shown={shown} onOpenRun={onOpenRun} />)
        : null}
    </>
  );
}

function SortHeader({ col, label, numeric, sort, onSort }: { col: string; label: string; numeric: boolean; sort: { col: string; dir: TableSortDir } | null; onSort: (col: string) => void }): ReactElement {
  const active = sort?.col === col;
  return (
    <th scope="col" className={numeric ? "num" : undefined} aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}>
      <button type="button" onClick={() => onSort(col)}>
        {label}
        {active ? (sort.dir === "asc" ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );
}

function RunLink({ run, onOpen, children }: { run: TaskRun | undefined; onOpen: (runId: string) => void; children: ReactNode }): ReactElement {
  if (!run) return <span>{children}</span>;
  return (
    <a
      href={hrefs.run(run.run_id)}
      onClick={(e: MouseEvent<HTMLAnchorElement>) => {
        if (!isPlainClick(e)) return;
        e.preventDefault();
        onOpen(run.run_id);
      }}
    >
      {children}
    </a>
  );
}

function SeedRow({ run, group, data, shown, onOpenRun }: { run: TaskRun; group: TaskGroup | null; data: TaskRuns; shown: readonly RunsColumn[]; onOpenRun: (runId: string) => void }): ReactElement {
  const cells = runCells(run, group, data);
  return (
    <tr className="seed">
      <td className="sel" />
      <td />
      <td className="name">
        <span>{`seed ${run.seed ?? "—"}`}</span>{" "}
        <RunLink run={run} onOpen={onOpenRun}>
          <span className="mono">{shortId(run.run_id)}</span>
        </RunLink>
      </td>
      {shown.map((c) => (
        <CellView key={c.id} col={c} cells={cells} best={false} asRun />
      ))}
    </tr>
  );
}

function CellView({ col, cells, best, asRun }: { col: RunsColumn; cells: Cells; best: boolean; asRun: boolean }): ReactElement {
  if (col.id.startsWith("param:")) return <td>{cells.params[col.id.slice(6)] || "—"}</td>;
  switch (col.id) {
    case "status":
      return (
        <td>
          <span className="sts">
            {cells.status.map(([s, n]) => (
              <StatusIcon key={s} status={s} title={`${n} ${s}`} label={asRun ? undefined : String(n)} />
            ))}
          </span>
        </td>
      );
    case "primary":
      return (
        <td className={`num${best ? " best" : ""}`}>
          {fmtScore(cells.mean)}
          {cells.sd !== null ? <span className="muted">{` ± ${fmtScore(cells.sd)}`}</span> : null}
        </td>
      );
    case "ci":
      return <td className="num muted">{cells.ci ? fmtInterval(cells.ci.lo, cells.ci.hi) : ""}</td>;
    case "delta":
      return (
        <td className="num">
          {cells.delta === null ? (
            "—"
          ) : (
            <span className={cells.deltaMuted ? "muted" : undefined} title={cells.deltaTitle}>
              {fmtDelta(cells.delta)}
            </span>
          )}
        </td>
      );
    case "launcher":
      return (
        <td>
          {cells.launcher.map((by) => (
            <Launcher key={by} who={by} />
          ))}
        </td>
      );
    case "host":
      return <td>{cells.host.join(", ")}</td>;
    case "gpu":
      return <td className="num">{cells.gpu === null ? "—" : fmtGpuHours(cells.gpu)}</td>;
    case "started":
      return <td className="muted">{cells.started ? fmtDate(cells.started) : "—"}</td>;
    case "commit":
      return <td className="mono">{cells.commit.join(", ")}</td>;
    case "tags":
      return (
        <td>
          {cells.tags.map((t) => (
            <span key={t} className="tag">
              {t}
            </span>
          ))}
        </td>
      );
    default:
      return <td />;
  }
}

/** Columns chip: a checkbox per column; Escape or a press outside closes it. */
function ColumnChooser({ columns, hidden, onChange }: { columns: readonly RunsColumn[]; hidden: readonly string[]; onChange: (next: string[]) => void }): ReactElement {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLSpanElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const group = useRef<HTMLDivElement>(null);
  useMenuFocus(open, group, button);
  useEffect(() => {
    if (!open) return;
    const away = (e: globalThis.MouseEvent): void => {
      if (!anchor.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const count = columns.filter((c) => !hidden.includes(c.id)).length;
  return (
    <span className="popover-anchor" ref={anchor}>
      <button ref={button} type="button" className="chip" aria-haspopup="true" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        Columns <b>{count}</b>
        <span className="chev">
          <Icon name="chevron" size={9} />
        </span>
      </button>
      {open ? (
        <div
          ref={group}
          className="popover"
          role="group"
          aria-label="Columns"
          onKeyDown={(e) => {
            menuArrowKeys(e);
            if (e.key !== "Escape") return;
            e.stopPropagation();
            setOpen(false);
            button.current?.focus();
          }}
        >
          {columns.map((c) => (
            <label key={c.id}>
              <input
                type="checkbox"
                checked={!hidden.includes(c.id)}
                onChange={() => onChange(hidden.includes(c.id) ? hidden.filter((h) => h !== c.id) : [...hidden, c.id])}
              />
              {c.label}
            </label>
          ))}
        </div>
      ) : null}
    </span>
  );
}

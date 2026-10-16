/**
 * The task's run list (spec 4.2 "Runs sidebar"): filter, Group (By config | Each run),
 * Sort and Columns chips, the superseded chip, `N/M shown`, and one row per identity:
 * colour swatch, name (rename with the pencil or a double click on the name), sub-line,
 * value and the eye. The list drives every panel: its state is in the URL
 * (`useRunSelection`), hover and focus go to the highlight store.
 *
 * A row is focusable and opens its run (a config: its latest run) on click or Enter; a
 * modified or middle click opens it in a new tab. A click on the name waits
 * `OPEN_DELAY_MS` so that a double click renames instead of leaving the page.
 */
import { type KeyboardEvent, type MouseEvent, type ReactElement, useEffect, useRef, useState } from "react";
import type { RunStatus, TaskRun, TaskRuns } from "../api/models";
import { Chip } from "../chrome/Chip";
import { EmptyState } from "../chrome/EmptyState";
import { FilterField } from "../chrome/FilterField";
import { Icon } from "../chrome/Icon";
import { menuArrowKeys, useMenuFocus } from "../chrome/menuFocus";
import { Launcher } from "../chrome/Launcher";
import { Segmented } from "../chrome/Segmented";
import { StatusIcon } from "../chrome/StatusIcon";
import { cx } from "../lib/cx";
import { colorFor } from "../lib/color";
import { fmtClock, fmtDate, fmtScore } from "../pages/components/format";
import { hrefs, isPlainClick } from "../pages/components/links";
import { RunName, toRenameTarget, withSeed } from "../run/RunName";
import { getHighlight, setHighlight } from "./highlight";
import {
  type GroupMode,
  type Identity,
  type Selection,
  type SortDir,
  SORT_CREATED,
  SORT_PRIMARY,
  identities,
  isSuperseded,
  keyHigherIsBetter,
  keyLabel,
  latestRun,
  listIdentities,
  scoreOf,
} from "./useRunSelection";
import "./task.css";

export interface RunsSidebarProps {
  data: TaskRuns;
  selection: Selection;
  onChange: (patch: Partial<Selection>) => void;
  /** Open a run page; a config opens its latest run. */
  onOpen: (runId: string) => void;
}

/** How long a click on a row's name waits for a second click (a double click renames). */
export const OPEN_DELAY_MS = 300;

const GROUPS: readonly (readonly [GroupMode, string])[] = [
  ["config", "By config"],
  ["run", "Each run"],
];

const arrow = (dir: SortDir): string => (dir === "desc" ? "↓" : "↑");

export function RunsSidebar({ data, selection, onChange, onOpen }: RunsSidebarProps): ReactElement {
  const all = identities(data, selection.group);
  const listed = listIdentities(selection, data);
  const visible = listed.filter((i) => !i.hidden).map((i) => i.id);
  const superseded = all.filter(isSuperseded).length;
  // identities the filter matches that only the superseded chip hides (explains a "0/N
  // shown"); only an empty list shows it, so only then list again
  const hiddenBySuperseded =
    listed.length > 0 || selection.showSuperseded ? 0 : listIdentities({ ...selection, showSuperseded: true }, data).length;
  // a stale `?col=` (the key is gone) shows the primary
  const column =
    selection.column !== data.primary && data.score_keys.includes(selection.column) ? selection.column : SORT_PRIMARY;
  const label = (key: string): string =>
    key === SORT_PRIMARY ? keyLabel(data.primary) : key === SORT_CREATED ? "created" : keyLabel(key);
  const scoreKeys = [SORT_PRIMARY, ...data.score_keys.filter((k) => k !== data.primary)];
  const sort = selection.sort;
  // a new score key sorts best first in its own direction; created sorts newest first
  const firstDir = (key: string): SortDir =>
    key !== SORT_CREATED && !keyHigherIsBetter(data, key === SORT_PRIMARY ? data.primary : key) ? "asc" : "desc";
  const pickSort = (key: string): void =>
    onChange({ sort: key === sort.key ? { key, dir: sort.dir === "desc" ? "asc" : "desc" } : { key, dir: firstDir(key) } });
  const toggle = (id: string): void =>
    onChange({
      hidden: selection.hidden.includes(id) ? selection.hidden.filter((h) => h !== id) : [...selection.hidden, id],
    });
  return (
    <aside className="runs" aria-label="Runs">
      <div className="runs-tools">
        <FilterField
          value={selection.filter}
          onChange={(filter) => onChange({ filter })}
          placeholder="Filter  lr=3e-4 · tag:final · status:running"
          label="Filter runs"
        />
        <div className="row">
          <Segmented label="Group" options={GROUPS} value={selection.group} onChange={(group) => onChange({ group })} />
          <ChipMenu
            name="Sort"
            value={`${label(sort.key)} ${arrow(sort.dir)}`}
            menuLabel="Sort by"
            items={[...scoreKeys, SORT_CREATED].map((key) => ({
              key,
              text: key === sort.key ? `${label(key)} ${arrow(sort.dir)}` : label(key),
              checked: key === sort.key,
            }))}
            onPick={pickSort}
          />
          <ChipMenu
            name="Columns"
            value={label(column)}
            menuLabel="Value column"
            items={scoreKeys.map((key) => ({ key, text: label(key), checked: key === column }))}
            onPick={(key) => onChange({ column: key })}
          />
          {superseded > 0 ? (
            <Chip
              on={!selection.showSuperseded}
              title="Runs tagged superseded are hidden by default"
              onClick={() => onChange({ showSuperseded: !selection.showSuperseded })}
            >
              {selection.showSuperseded ? "Superseded shown" : `${superseded} superseded hidden`}
            </Chip>
          ) : null}
          <span className="count">{`${visible.length}/${all.length} shown`}</span>
        </div>
      </div>
      <div className="runs-head" aria-hidden="true">
        <span />
        <span>{selection.group === "config" ? "Config · seeds" : "Run"}</span>
        <span className="num">{label(column)}</span>
        <span />
      </div>
      <div className="runs-list" role="list" aria-label="Run list">
        {listed.map((item) => (
          <SidebarRow
            key={item.id}
            item={item}
            color={colorFor(item.id, visible)}
            column={column}
            onToggle={() => toggle(item.id)}
            onOpen={onOpen}
          />
        ))}
      </div>
      {all.length === 0 ? (
        <EmptyState title="No runs yet" />
      ) : listed.length === 0 ? (
        <EmptyState
          title="No runs match"
          body={
            hiddenBySuperseded > 0 ? (
              <button type="button" className="linkish" title="Show superseded runs" onClick={() => onChange({ showSuperseded: true })}>
                {`${hiddenBySuperseded} hidden by superseded`}
              </button>
            ) : undefined
          }
        />
      ) : null}
    </aside>
  );
}

interface MenuItem {
  key: string;
  text: string;
  checked: boolean;
}

interface ChipMenuProps {
  /** Chip text before the value: "Sort", "Columns". */
  name: string;
  value: string;
  menuLabel: string;
  items: readonly MenuItem[];
  onPick: (key: string) => void;
}

/** A chip with a chevron that opens a one-choice menu; Escape or a press outside closes it. */
function ChipMenu({ name, value, menuLabel, items, onPick }: ChipMenuProps): ReactElement {
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLSpanElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  useMenuFocus(open, menu, button);
  useEffect(() => {
    if (!open) return;
    const away = (e: globalThis.MouseEvent): void => {
      if (!anchor.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  return (
    <span className="popover-anchor" ref={anchor}>
      <button
        ref={button}
        type="button"
        className="chip"
        aria-haspopup="menu"
        aria-expanded={open}
        title={menuLabel}
        onClick={() => setOpen((o) => !o)}
      >
        {name} <b>{value}</b>
        <span className="chev">
          <Icon name="chevron" size={9} />
        </span>
      </button>
      {open ? (
        <div
          ref={menu}
          className="popover"
          role="menu"
          aria-label={menuLabel}
          onKeyDown={(e) => {
            menuArrowKeys(e);
            if (e.key !== "Escape") return;
            e.stopPropagation();
            setOpen(false);
            button.current?.focus();
          }}
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitemradio"
              aria-checked={item.checked}
              onClick={() => {
                setOpen(false);
                onPick(item.key);
              }}
            >
              {item.text}
            </button>
          ))}
        </div>
      ) : null}
    </span>
  );
}

interface RowProps {
  item: Identity;
  color: string;
  /** Score key of the value column (`SORT_PRIMARY`: the primary, with ± sd for a config). */
  column: string;
  onToggle: () => void;
  onOpen: (runId: string) => void;
}

/** What a rename of the identity edits: shown name, derived name (Reset), renamed. */
function renameTarget(item: Identity, latest: TaskRun | undefined): { derived: string; renamed: boolean } {
  if (item.kind === "run" && latest) return { derived: withSeed(latest.derived_name, latest.seed), renamed: latest.renamed };
  const renamed = item.runs.some((r) => r.renamed);
  return { derived: renamed && latest ? latest.derived_name : item.name, renamed };
}

function SidebarRow({ item, color, column, onToggle, onOpen }: RowProps): ReactElement {
  const latest = latestRun(item.runs);
  const best = item.kind === "group" && item.group?.is_best === true;
  const pending = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // a row that leaves the list drops its pending open and its highlight
  useEffect(
    () => () => {
      clearTimeout(pending.current);
      if (getHighlight() === item.id) setHighlight(null);
    },
    [item.id],
  );
  const inControl = (target: EventTarget): boolean =>
    target instanceof Element && target.closest("button, input, .run-name.editing") !== null;
  const newTab = (): void => {
    if (latest) window.open(hrefs.run(latest.run_id), "_blank", "noopener");
  };
  const onClick = (e: MouseEvent<HTMLDivElement>): void => {
    if (!latest || inControl(e.target)) return;
    if (!isPlainClick(e)) {
      newTab();
      return;
    }
    clearTimeout(pending.current);
    if (e.detail > 1) return;
    const runId = latest.run_id;
    if (e.target instanceof Element && e.target.closest(".rn-t")) {
      pending.current = setTimeout(() => onOpen(runId), OPEN_DELAY_MS);
    } else onOpen(runId);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (e.key !== "Enter" || e.target !== e.currentTarget || !latest) return;
    e.preventDefault();
    onOpen(latest.run_id);
  };
  const value = column === SORT_PRIMARY ? item.value : scoreOf(item, column);
  const name = renameTarget(item, latest);
  return (
    <div
      role="listitem"
      tabIndex={0}
      className={cx("rrow", item.hidden && "off", best && "best")}
      onClick={onClick}
      onAuxClick={(e) => {
        if (e.button === 1 && !inControl(e.target)) newTab();
      }}
      onDoubleClick={() => clearTimeout(pending.current)}
      onKeyDown={onKeyDown}
      onMouseEnter={() => setHighlight(item.id)}
      onMouseLeave={() => setHighlight(null)}
      onFocus={() => setHighlight(item.id)}
      onBlur={() => setHighlight(null)}
    >
      <span className="sw" style={item.hidden ? undefined : { background: color }} aria-hidden="true" />
      <div className="rname">
        <div className="t" title={item.name}>
          <RunName
            runId={latest?.run_id ?? item.id}
            runs={item.kind === "group" ? item.runs.map(toRenameTarget) : undefined}
            display={item.name}
            derived={name.derived}
            renamed={name.renamed}
            editOn="dblclick"
            label={`Rename ${item.name}`}
          />
        </div>
        <SubLine item={item} latest={latest} />
      </div>
      <div className="rval">
        {fmtScore(value)}
        {column === SORT_PRIMARY && item.sd !== null ? <small>{`± ${fmtScore(item.sd)}`}</small> : null}
      </div>
      <button
        type="button"
        className="eye"
        data-identity={item.id}
        aria-pressed={!item.hidden}
        aria-label={`${item.hidden ? "Show" : "Hide"} ${item.name}`}
        title={item.hidden ? "Show in all panels" : "Hide in all panels"}
        onClick={onToggle}
      >
        <Icon name={item.hidden ? "eye-off" : "eye"} />
      </button>
    </div>
  );
}

function SubLine({ item, latest }: { item: Identity; latest: TaskRun | undefined }): ReactElement {
  const count = (statuses: readonly RunStatus[]): number => item.runs.filter((r) => statuses.includes(r.status)).length;
  const tally = (n: number, status: RunStatus): ReactElement | null =>
    n > 0 ? <StatusIcon status={status} label={String(n)} title={`${n} ${status}`} /> : null;
  const final = item.runs.some((r) => r.tags.includes("final"));
  return (
    <span className="s">
      {latest ? <Launcher who={latest.created_by} /> : null}
      {item.kind === "group" ? (
        <>
          <span>{`${item.runs.length} seed${item.runs.length === 1 ? "" : "s"}`}</span>
          {tally(count(["running"]), "running")}
          {tally(count(["queued"]), "queued")}
          {tally(count(["failed", "lost"]), "failed")}
        </>
      ) : latest ? (
        <>
          <StatusIcon status={latest.status} iconOnly title={latest.status} />
          <span title={fmtDate(latest.created_at)}>{fmtClock(latest.created_at)}</span>
        </>
      ) : null}
      {final ? <span className="final">final</span> : null}
    </span>
  );
}

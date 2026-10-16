/** Run header (spec 4.3, mockup .rhead): swatch, name, status pill, actions, hypothesis, banners, tabs. */
import { STATUS_WORD, StatusIcon, type StatusKind } from "../chrome/StatusIcon";
import { AppLink, hrefs } from "../pages/components/links";
import { RunActions } from "../pages/components/RunActions";
import { StateBanner } from "../pages/components/StateBanner";
import { RUN_TABS, RUN_TAB_LABELS, type RunContext, type RunTab } from "./runContext";
import { RunName } from "./RunName";

/** The pill's word: the status word, capitalised ("Finished"). */
const pillWord = (state: StatusKind): string => STATUS_WORD[state].charAt(0).toUpperCase() + STATUS_WORD[state].slice(1);

/** The pill's state: a run on an unreachable host is stale (derived on the hub), else its status. */
export function pillState(ctx: Pick<RunContext, "phase" | "record">): StatusKind {
  return ctx.phase === "stale" ? "stale" : ctx.record.status;
}

export function RunHeader({ ctx, tab }: { ctx: RunContext; tab: RunTab }) {
  const { record, title } = ctx;
  const state = pillState(ctx);
  return (
    <header className="rhead">
      <div className="rhead-top">
        <span className="sw lg" data-color={ctx.identity.color} style={{ background: ctx.identity.color }} aria-hidden="true" />
        <h1>
          <RunName runId={ctx.runId} display={title.display} derived={title.derived} renamed={title.renamed} />
        </h1>
        <span className={`pill ${state}`}>
          <StatusIcon status={state} label={pillWord(state)} />
        </span>
        <span className="sp" />
        <RunActions
          record={record}
          phase={ctx.phase}
          hostName={ctx.host?.name ?? null}
          served={ctx.detail.served === true}
          hostsLoaded={ctx.hostsLoaded}
          inferStage={ctx.inferStage}
          compareHref={ctx.compareHref}
        />
      </div>
      {record.hypothesis ? <p className="rhyp">{record.hypothesis}</p> : null}
      {title.renamed ? <p className="rderived">{`Renamed. Derived name: ${title.derived}`}</p> : null}
      <StateBanner
        record={record}
        phase={ctx.phase}
        host={ctx.host}
        conn={ctx.detail.host_state ?? null}
        now={ctx.now}
        reason={ctx.lostWhy}
      />
      <nav className="tabs" role="tablist" aria-label="Run">
        {RUN_TABS.map((t) => (
          <AppLink
            key={t}
            role="tab"
            aria-selected={t === tab}
            className={t === tab ? "on" : undefined}
            href={hrefs.run(ctx.runId, { tab: t })}
          >
            {RUN_TAB_LABELS[t]}
          </AppLink>
        ))}
      </nav>
    </header>
  );
}

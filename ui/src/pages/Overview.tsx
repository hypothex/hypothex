/**
 * Overview screen (spec 8.3.1, 8A.8): status headline; hosts (GPUs, SLURM, queue, cost);
 * runs by launcher; recent ideas; running; failures with a link to stderr; projects table.
 *
 * With hosts configured, the headline reads `12 running, 11 waiting. dgx stale 4m` and the
 * metaline shows free GPUs, cost today, the hub's hx version and the host count, one per
 * row of the Hosts table with the hub's own row (mockup
 * `docs/mockups/phase2/shot-overview-*`). The hosts list always has the hub's own `local`
 * row; with no other host both stay as in phase 1 (plus `$N today` once runs cost money). A
 * host stale for longer than the hub's `stale_banner_hours` (default 24) gets a banner (spec
 * 5.6); its runs stay stale, never lost.
 */
import { useQuery } from "@tanstack/react-query";
import { Fragment } from "react";
import { api } from "../api/client";
import { useHosts, useOverview } from "../api/queries";
import { Figure } from "./components/Figure";
import { Unbroken } from "./components/Headline";
import {
  HostsPanel,
  fmtMoney,
  hostTotals,
  hostsHeadline,
  hostsMetaline,
  longStale,
  remoteRows,
  staleBannerHours,
  useNow,
} from "./components/HostsPanel";
import { IdeaList } from "./components/IdeaList";
import { FailureList, ProjectsTable, RunningList } from "./components/OverviewLists";
import { ErrorBox, Loading } from "./components/QueryState";
import { RunTimeline } from "./components/RunTimeline";
import { PageStyles } from "./components/styles";
import type { OverviewSummary } from "./components/types";

/** The hub's hx version from its environment descriptor; null until known or on error. */
function useHubVersion(): string | null {
  const env = useQuery({
    queryKey: ["environment"],
    queryFn: ({ signal }) => api.environment(signal),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const version = env.data?.hx_version;
  return typeof version === "string" ? version : null;
}

function OverviewBody({ summary }: { summary: OverviewSummary }) {
  const hosts = useHosts();
  const hubVersion = useHubVersion();
  const now = useNow();
  // TanStack keeps the last good data when a later poll fails; on an error the page goes
  // back to the phase 1 headline and counts, like the first-load failure
  const rows = hosts.error ? [] : (hosts.data ?? []);
  const remote = remoteRows(rows);
  // the overview's cost today covers every run (hub runs too); the hosts' sum is the fallback
  const hostSums = hostTotals(rows, now);
  const totals = { ...hostSums, usdToday: summary.cost_today_usd ?? hostSums.usdToday };
  const withHosts = remote.length > 0;
  const hours = staleBannerHours(rows);
  const gone = longStale(remote, now, hours);
  const hubCost = summary.cost_today_usd ?? 0;
  return (
    <>
      <h1 className="headline">
        <Unbroken text={withHosts ? hostsHeadline(summary.counts, totals) : summary.headline} />
      </h1>
      <p className="metaline">
        {withHosts
          ? hostsMetaline(totals, hubVersion, rows.length).map((text) => <span key={text}>{text}</span>)
          : [
              ...Object.entries(summary.counts).map(([key, value]) => <span key={key}>{`${value} ${key}`}</span>),
              ...(hubCost > 0 ? [<span key="cost today">{`${fmtMoney(hubCost)} today`}</span>] : []),
            ]}
      </p>
      {gone.length > 0 ? (
        <p
          className="hosts-banner"
          role="status"
          title={`No answer for more than ${hours} h. Its runs stay stale, not lost: only the host marks a run lost.`}
        >
          {gone.map((h, i) => (
            <Fragment key={h.name}>
              {i > 0 ? ", " : null}
              <b>{h.name}</b>
              {` unreachable ${h.age}`}
            </Fragment>
          ))}
        </p>
      ) : null}
      <Figure
        letter="a"
        title="Hosts"
        aside={totals.usdToday > 0 ? `${fmtMoney(totals.usdToday)} today` : undefined}
      >
        {hosts.error ? (
          <ErrorBox error={hosts.error} />
        ) : hosts.data ? (
          <HostsPanel hosts={hosts.data} runs={summary.running} hubVersion={hubVersion} now={now} />
        ) : (
          <Loading />
        )}
      </Figure>
      <Figure letter="b" title="Runs by launcher">
        <RunTimeline items={summary.timeline} />
      </Figure>
      <div className="ov-grid">
        <div>
          <Figure letter="c" title="Ideas">
            <IdeaList ideas={summary.ideas} />
          </Figure>
        </div>
        <div className="side">
          <Figure letter="d" title="Running">
            <RunningList runs={summary.running} />
          </Figure>
          <Figure letter="e" title="Failures">
            <FailureList failures={summary.failures} />
          </Figure>
          <Figure letter="f" title="Projects">
            <ProjectsTable projects={summary.projects} />
          </Figure>
        </div>
      </div>
    </>
  );
}

export function OverviewPage() {
  const overview = useOverview();
  return (
    <div className="page">
      <PageStyles />
      <p className="crumb">All projects</p>
      {overview.error ? <ErrorBox error={overview.error} /> : null}
      {overview.data ? (
        <OverviewBody summary={overview.data} />
      ) : overview.error ? null : (
        <Loading />
      )}
    </div>
  );
}

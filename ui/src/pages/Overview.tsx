/**
 * Overview screen (spec 8.3.1): status headline; runs by launcher; recent ideas;
 * running; failures with a link to stderr; projects table.
 */
import { useOverview } from "../api/queries";
import { Figure } from "./components/Figure";
import { IdeaList } from "./components/IdeaList";
import { FailureList, ProjectsTable, RunningList } from "./components/OverviewLists";
import { ErrorBox, Loading } from "./components/QueryState";
import { RunTimeline } from "./components/RunTimeline";
import { PageStyles } from "./components/styles";
import type { OverviewSummary } from "./components/types";
import { Unbroken } from "./components/Headline";

function OverviewBody({ summary }: { summary: OverviewSummary }) {
  return (
    <>
      <h1 className="headline">
        <Unbroken text={summary.headline} />
      </h1>
      <p className="metaline">
        {Object.entries(summary.counts).map(([key, value]) => (
          <span key={key}>{`${value} ${key}`}</span>
        ))}
      </p>
      <Figure letter="a" title="Runs by launcher">
        <RunTimeline items={summary.timeline} />
      </Figure>
      <div className="ov-grid">
        <div>
          <Figure letter="b" title="Ideas">
            <IdeaList ideas={summary.ideas} />
          </Figure>
        </div>
        <div className="side">
          <Figure letter="c" title="Running">
            <RunningList runs={summary.running} />
          </Figure>
          <Figure letter="d" title="Failures">
            <FailureList failures={summary.failures} />
          </Figure>
          <Figure letter="e" title="Projects">
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

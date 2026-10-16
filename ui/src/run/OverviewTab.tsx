/** Run Overview tab (spec 4.3): queue (queued runs), scores, where it ranks, curves, kind panels, files. */
import { useMemo, useState } from "react";
import { useAllRuns, useOverview, useRunTraces } from "../api/queries";
import { Fit } from "../charts/Fit";
import { ScoreStrip } from "../charts/ScoreStrip";
import { fmtDelta, fmtScore, fmtScoreUnit } from "../pages/components/format";
import { readsTraces } from "../pages/components/KindPanels";
import { AppLink, hrefs } from "../pages/components/links";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { QueuePanel, queueRows, queuedRunsQuery } from "../pages/components/QueuePanel";
import { hostLabel } from "../pages/components/remote";
import { pickCurves, stepMetrics } from "./curves";
import { FileList } from "./FileList";
import { filesHost, overviewFiles } from "./files";
import { KindSection, runPanelSpecs } from "./KindSection";
import { MetricPanels, useRunCurves } from "./MetricPanels";
import type { RunContext } from "./runContext";
import { type RankModel, type ScoreTile, rankModel, scoreTiles } from "./scores";

const SHOWN_TILES = 8;

function Tile({ tile, unit }: { tile: ScoreTile; unit: string }) {
  const why = tile.delta === null || tile.sd === null ? undefined : `${tile.noise ? "inside" : "outside"} 1 sd (${fmtScore(tile.sd)}) of the config's seeds`;
  const cls = tile.noise ? "muted" : tile.better === null ? "ink2" : tile.better ? "delta-up" : "delta-dn";
  return (
    <div className={tile.primary ? "tile prim" : "tile"}>
      <div className="tk">
        <span className="tl" title={tile.label}>
          {tile.label}
        </span>
        {tile.primary ? <span className="star">primary</span> : null}
        {tile.old ? <span className="old">old version</span> : null}
      </div>
      <div className="tv">
        {tile.error ? (
          <span className="err" title={tile.error}>
            error
          </span>
        ) : tile.primary ? (
          fmtScoreUnit(tile.value, unit)
        ) : (
          fmtScore(tile.value)
        )}
      </div>
      <div className="td" title={why}>
        {tile.delta === null ? null : (
          <>
            <span className={cls}>{fmtDelta(tile.delta)}</span>
            <span className="muted"> vs config mean</span>
          </>
        )}
      </div>
    </div>
  );
}

function ScoreTiles({ tiles, unit }: { tiles: ScoreTile[]; unit: string }) {
  const [all, setAll] = useState(false);
  const shown = all ? tiles : tiles.slice(0, SHOWN_TILES);
  return (
    <>
      <div className="tiles">
        {shown.map((t) => (
          <Tile key={t.id} tile={t} unit={unit} />
        ))}
      </div>
      {tiles.length > SHOWN_TILES ? (
        <button type="button" className="btn sm ghost" onClick={() => setAll(!all)}>
          {all ? "Fewer scores" : `All ${tiles.length} scores`}
        </button>
      ) : null}
    </>
  );
}

function RankStrip({ rank, label }: { rank: RankModel; label: string }) {
  return (
    <div className="rank">
      <div className="rank-h">
        <span>Where it ranks</span>
        <span className="muted">{`${label} · ${rank.summary}`}</span>
      </div>
      <Fit minHeight={46}>{(width) => <ScoreStrip width={width} marks={rank.marks} band={rank.band} />}</Fit>
      <div className="rank-legend">
        <span>
          <i className="dot" style={{ background: rank.color }} />
          this run
        </span>
        {rank.seeds > 1 ? (
          <span>
            <i className="dot faint" style={{ background: rank.color }} />
            other seeds
          </span>
        ) : null}
        {rank.configs > 1 ? (
          <span>
            <i className="tick" />
            other configs
          </span>
        ) : null}
        {rank.band ? (
          <span>
            <i className="band" />
            best config, 95% CI
          </span>
        ) : null}
      </div>
    </div>
  );
}

function QueueSection({ ctx }: { ctx: RunContext }) {
  const { record, host, now } = ctx;
  const queued = useAllRuns(queuedRunsQuery(record.environment_id), true);
  const names = useOverview().data?.names;
  const where = hostLabel(record, host);
  return (
    <section aria-label="Queue">
      <h3>
        Queue <span className="muted">{host ? `${host.name}, ${host.queue} waiting` : where}</span>
      </h3>
      {queued.error ? (
        <ErrorBox error={queued.error} />
      ) : queued.data ? (
        <>
          <QueuePanel host={host} hostName={where} runId={ctx.runId} rows={queueRows(queued.data.runs, record.environment_id, now, record, names)} />
          {queued.data.complete ? null : <p className="muted">{`first ${queued.data.runs.length} queued runs on ${where}`}</p>}
        </>
      ) : (
        <Loading />
      )}
    </section>
  );
}

function CurvesSection({ ctx, metrics }: { ctx: RunContext; metrics: string[] }) {
  const curves = useRunCurves(ctx, metrics);
  return (
    <section aria-label="Curves">
      <h3>
        Curves
        <AppLink className="more" href={hrefs.run(ctx.runId, { tab: "charts" })}>
          All charts
        </AppLink>
      </h3>
      <MetricPanels ctx={ctx} metrics={metrics} height={150} curves={curves} />
    </section>
  );
}

export function OverviewTab({ ctx }: { ctx: RunContext }) {
  const { detail, record, phase, taskRuns, identity } = ctx;
  const waiting = phase === "queued" || phase === "pending";
  const tiles = useMemo(
    () =>
      scoreTiles(detail.scores, {
        primary: taskRuns?.primary ?? null,
        higherIsBetter: taskRuns?.higher_is_better ?? true,
        versions: taskRuns?.metric_versions ?? null,
        group: identity.run ? [identity.run, ...identity.siblings] : [],
      }),
    [detail.scores, taskRuns, identity],
  );
  const rank = taskRuns ? rankModel(taskRuns, ctx.runId, identity.color) : null;
  const curves = pickCurves(stepMetrics(detail.metric_names), taskRuns?.primary ?? null);
  const wantsTraces = (ctx.kind?.run_view ?? []).some(readsTraces);
  const traces = useRunTraces(ctx.runId, wantsTraces && !waiting);
  const specs = useMemo(
    () => runPanelSpecs(ctx.kind, traces.data?.length, detail.metric_names),
    [ctx.kind, traces.data, detail.metric_names],
  );
  const primaryLabel = tiles.find((t) => t.primary)?.label ?? taskRuns?.primary ?? "";
  return (
    <div className="rmain">
      {ctx.kindError ? <ErrorBox error={ctx.kindError} /> : null}
      {phase === "queued" ? <QueueSection ctx={ctx} /> : null}
      {tiles.length > 0 || rank ? (
        <section aria-label="Scores">
          <h3>Scores</h3>
          {tiles.length > 0 ? <ScoreTiles tiles={tiles} unit={taskRuns?.unit ?? ""} /> : null}
          {rank ? <RankStrip rank={rank} label={primaryLabel} /> : null}
        </section>
      ) : null}
      {curves.length > 0 && !waiting ? <CurvesSection ctx={ctx} metrics={curves} /> : null}
      {record.task && !waiting ? (
        <KindSection
          project={record.project}
          task={record.task}
          runId={ctx.runId}
          specs={specs}
          example={ctx.example}
          currentGroupId={identity.run?.group_id}
          runStatus={record.status}
        />
      ) : null}
      <section aria-label="Files">
        <h3>
          Files <span className="muted">{`on ${filesHost(detail)}`}</span>
        </h3>
        <FileList rows={overviewFiles(detail)} />
      </section>
    </div>
  );
}

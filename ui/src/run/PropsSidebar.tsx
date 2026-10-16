/** Run properties sidebar (spec 4.3, mockup .rside): facts, config, tags, notes, ids. */
import { type ReactNode, useState } from "react";
import { api } from "../api/client";
import { hasScope } from "../api/scopes";
import { useMe, RUN_EVENT_INVALIDATES } from "../api/queries";
import { Launcher } from "../chrome/Launcher";
import { StatusIcon } from "../chrome/StatusIcon";
import { CopyButton } from "../pages/components/CopyButton";
import { fmtCount, fmtDate, fmtDuration, runSeconds, shortId } from "../pages/components/format";
import { AppLink, hrefs } from "../pages/components/links";
import { Notes } from "../pages/components/Notes";
import { ErrorBox } from "../pages/components/QueryState";
import { costShown, sweepCrumb } from "../pages/components/remote";
import { useAction } from "../pages/components/useAction";
import { gitLine } from "../pages/components/WhereList";
import { commitText, configRows, gpuUse, hostText, placementExtras, statusText } from "./props";
import { pillState } from "./RunHeader";
import type { RunContext } from "./runContext";

function Prop({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="prop">
      <span className="k">{k}</span>
      <span className="v">{children}</span>
    </div>
  );
}

/** The run's tags with a remove button each and "+ Add" (Enter adds, Escape cancels). */
export function TagEditor({ runId, tags, served }: { runId: string; tags: string[]; served: boolean }) {
  const me=useMe();
  const writable=hasScope(me.data,"launch");
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  const close = () => {
    setAdding(false);
    setText("");
  };
  const change = useAction<unknown, { add?: string[]; remove?: string[] }>({
    send: (body, opts) => api.tagRun(runId, body, opts),
    invalidate: RUN_EVENT_INVALIDATES,
    onSuccess: close,
  });
  const submit = () => {
    const tag = text.trim();
    if (tag === "" || tags.includes(tag)) close();
    else change.run({ add: [tag] });
  };
  return (
    <div className="tagrow">
      {tags.map((tag) => (
        <span key={tag} className="tag">
          {tag}
          <button
            type="button"
            className="tag-x"
            aria-label={`Remove tag ${tag}`}
            disabled={!writable || !served || change.pending}
            onClick={() => change.run({ remove: [tag] })}
          >
            ×
          </button>
        </span>
      ))}
      {adding ? (
        <input
          className="tag-in"
          aria-label="New tag"
          autoFocus
          value={text}
          disabled={!writable || change.pending}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              submit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              close();
            }
          }}
        />
      ) : (
        <button type="button" className="tag add" disabled={!writable || !served} onClick={() => setAdding(true)}>
          + Add
        </button>
      )}
      {change.error ? <ErrorBox error={change.error} /> : null}
    </div>
  );
}

export function PropsSidebar({ ctx }: { ctx: RunContext }) {
  const { record, detail, phase, host, now } = ctx;
  const state = pillState(ctx);
  const sweep = sweepCrumb(record, ctx.hubEnvId);
  const cost = costShown(record.cost, host);
  const seconds = runSeconds(record, now);
  const git = gitLine(record.git);
  const commit = commitText(record.git);
  const use = gpuUse(record, phase, host);
  const extras = ctx.remote ? placementExtras(record, phase, host) : [];
  const varying = ctx.taskRuns?.varying_keys ?? [];
  const config = configRows(record, varying, ctx.identity.siblings.length > 0);
  const folder = detail.paths.run_dir?.split("/").filter(Boolean).pop() ?? "";
  const usage = record.usage;
  return (
    <aside className="rside" aria-label="Properties">
      <div className="pgroup">
        {record.task ? (
          <Prop k="Task">
            <AppLink className="lnk" href={hrefs.task(record.project, record.task)}>{`${record.project} / ${record.task}`}</AppLink>
            {ctx.kind ? <span className="tag">{ctx.kind.kind}</span> : null}
          </Prop>
        ) : (
          <Prop k="Project">{record.project}</Prop>
        )}
        <Prop k="Status">
          <StatusIcon status={state} label={statusText(record, phase, host, now, ctx.lostWhy)} />
        </Prop>
        {record.owner && <Prop k="Owner">@{record.owner}</Prop>}
        <Prop k="Launcher">
          <Launcher who={record.created_by} />
        </Prop>
        <Prop k="Host">{hostText(record, phase, host)}</Prop>
        {use ? <Prop k="GPU use">{use}</Prop> : null}
        {extras.map((row) => (
          <Prop key={row.key} k={row.key}>
            <span className={row.mono ? "mono" : undefined}>{row.value}</span>
            {row.note ? <small>{row.note}</small> : null}
            {row.copy ? <CopyButton text={row.copy} label={`${row.key} ${row.copy}`} /> : null}
          </Prop>
        ))}
        <Prop k="Started">{fmtDate(record.started_at ?? record.created_at)}</Prop>
        {seconds !== null ? <Prop k="Duration">{fmtDuration(seconds)}</Prop> : null}
        {commit ? (
          <Prop k="Commit">
            <span className="mono" title={git ? `${git.ref} — ${git.text}` : undefined}>
              {commit}
            </span>
          </Prop>
        ) : null}
        {record.parent ? (
          <Prop k="Parent">
            <AppLink className="lnk mono" href={hrefs.run(record.parent)}>
              {shortId(record.parent)}
            </AppLink>
            {record.kind === "infer" ? <span className="tag">infer</span> : null}
          </Prop>
        ) : null}
        {sweep ? (
          <Prop k="Sweep">
            {sweep.href ? (
              <AppLink className="lnk" href={sweep.href}>
                {sweep.id}
              </AppLink>
            ) : (
              <span title={sweep.why ?? undefined}>{sweep.id}</span>
            )}
          </Prop>
        ) : null}
        {cost ? (
          <Prop k="Cost">
            <span title={cost.note}>{cost.value}</span>
          </Prop>
        ) : null}
        {usage ? <Prop k="Usage">{`${fmtCount(usage.tokens_in)} in · ${fmtCount(usage.tokens_out)} out · ${usage.calls} calls`}</Prop> : null}
      </div>
      <div className="pgroup">
        <div className="ph4">
          Config
          {varying.length > 0 ? (
            <span className="muted" title="Values that differ between this task's configs; the run is named by them">
              tinted = varies in task
            </span>
          ) : null}
        </div>
        {config.length > 0 ? (
          config.map((row) => (
            <Prop key={row.key} k={row.key}>
              {row.varies ? <span className="chg">{row.value}</span> : row.value}
            </Prop>
          ))
        ) : (
          <p className="muted">No params</p>
        )}
      </div>
      <div className="pgroup">
        <div className="ph4">Tags</div>
        <TagEditor runId={ctx.runId} tags={record.tags} served={detail.served !== false} />
      </div>
      <div className="pgroup">
        <div className="ph4">Notes</div>
        <Notes runId={ctx.runId} notes={detail.notes} />
      </div>
      <div className="pgroup ids mono">{`run ${record.run_id}${folder && folder !== record.run_id ? ` · ${folder}` : ""}`}</div>
    </aside>
  );
}

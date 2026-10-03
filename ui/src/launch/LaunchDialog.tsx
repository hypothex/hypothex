/**
 * Launch dialog (spec 8A.5, 8A.8; mockups docs/mockups/phase2/shot-launch*.png).
 *
 * Pick a host (the hub first, then every host with its free GPUs, queue and state), GPUs per
 * run and the queue (SSH hosts) or sbatch fields (SLURM hosts), seeds, a command template
 * with `{seed}`, and a required hypothesis. The preview shows the first seed's command as it
 * will run. Launch posts one run per seed; every POST carries `<attempt>.s<seed>` as its
 * `command_id`, and the attempt id changes only when the form changes, so a double click or
 * a retry after a refused seed never starts a seed twice (spec 5.3). The seeds that did
 * start are remembered and never sent again, even after an edit gives a new attempt id.
 */
import { useQueryClient } from "@tanstack/react-query";
import {
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";

import { newCommandId } from "../api/client";
import type { RunRecord } from "../api/models";
import { REMOTE_RUN_INVALIDATES } from "../api/queries";
import { shellJoin } from "../pages/components/format";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { launchCli, sbatchLine } from "./cli";
import { SEED_HINT, templateSegments } from "./command";
import { type Carry, DEFAULT_DRAFT, type DraftCheck, type LaunchDraft, NO_CARRY, checkDraft } from "./draft";
import { launchSeeds, useLaunchHosts } from "./launchApi";
import {
  type Availability,
  type LaunchHost,
  type LaunchPlan,
  type LaunchSpec,
  SLURM_MAX_GPUS,
  availability,
  freeGpus,
  gpuCells,
  gpuLimit,
  gpusForHost,
  hostTitle,
  launchSummary,
  pickHost,
  posRange,
  stateLabel,
} from "./plan";
import { LaunchStyles } from "./styles";

export interface LaunchDialogProps {
  project: string;
  task: string | null;
  /** The project repo on the hub (`TaskDetail.repo`): sent only with a launch on the hub. */
  repo: string;
  /** Pinned commit (Rerun sweep: `pinnedCommit(template)`); absent: the hub pins its checkout. */
  commit?: string | null;
  title?: string;
  initial?: Partial<LaunchDraft>;
  /** Params and vars of the template run, sent with every seed. */
  carry?: Carry;
  onClose: () => void;
  onLaunched: (records: RunRecord[], host: string) => void;
}

type CopyState = "idle" | "copied" | "failed";

const COPY_TEXT: Record<CopyState, string> = {
  idle: "Copy as CLI",
  copied: "Copied",
  failed: "Clipboard blocked",
};

interface Failure {
  seed: number;
  message: string;
  /** Seeds started by this dialog so far, and seeds still to send. */
  done: number;
  left: number;
}

/** Seeds this dialog has started, in launch order, with their records. */
interface Launched {
  seeds: number[];
  records: RunRecord[];
}

const NOTHING_LAUNCHED: Launched = { seeds: [], records: [] };

type Update = (patch: Partial<LaunchDraft>) => void;

interface RowProps {
  draft: LaunchDraft;
  check: DraftCheck;
  update: Update;
}

function Stepper({
  label,
  value,
  max,
  onChange,
}: {
  label: string;
  value: number;
  max: number;
  onChange: (n: number) => void;
}) {
  return (
    <span className="stp">
      <button
        type="button"
        aria-label={`Fewer ${label}`}
        disabled={value <= 0}
        onClick={() => onChange(Math.max(0, value - 1))}
      >
        −
      </button>
      <output aria-label={label}>{value}</output>
      <button
        type="button"
        aria-label={`More ${label}`}
        disabled={value >= max}
        onClick={() => onChange(Math.min(max, value + 1))}
      >
        +
      </button>
    </span>
  );
}

function HostLoad({ host }: { host: LaunchHost }) {
  if (host.kind === "slurm") {
    return (
      <span className="small">{host.slurm ? `${host.slurm.running} run, ${host.slurm.pending} pend` : "·"}</span>
    );
  }
  if (host.gpus.length === 0) return <span className="small">no GPU</span>;
  return (
    <span className="mini" aria-hidden="true">
      {gpuCells(host).map((cell, i) => (
        <i key={i} className={cell} />
      ))}
    </span>
  );
}

function hostRight(host: LaunchHost, av: Availability, now: number): ReactNode {
  if (host.state !== "connected") return stateLabel(host, now);
  if (!av.ok) return "no path";
  if (host.kind === "slurm") return "";
  return (
    <>
      <b>{freeGpus(host).length}</b> free
    </>
  );
}

function HostPicker({
  hosts,
  selected,
  project,
  now,
  onPick,
}: {
  hosts: LaunchHost[];
  selected: string | null;
  project: string;
  now: number;
  onPick: (host: LaunchHost) => void;
}) {
  return (
    <div className="hp" role="radiogroup" aria-label="Host">
      {hosts.map((h) => {
        const av = availability(h, project, now);
        const on = h.name === selected;
        const cls = [on ? "on" : "", av.ok ? "" : "off"].filter(Boolean).join(" ");
        return (
          <label key={h.name} className={cls || undefined} title={av.ok ? hostTitle(h) : av.reason}>
            <input
              type="radio"
              name="hx-launch-host"
              value={h.name}
              aria-label={h.name}
              checked={on}
              disabled={!av.ok}
              onChange={() => onPick(h)}
            />
            <span className="nm">{h.name}</span>
            <span className="tag">{h.kind}</span>
            <HostLoad host={h} />
            <span className="fr-n">{hostRight(h, av, now)}</span>
            <span className="qq">{h.kind === "slurm" ? "" : `q ${h.queue}`}</span>
          </label>
        );
      })}
    </div>
  );
}

function GpuLine({ plan }: { plan: LaunchPlan }) {
  return (
    <span className="small r" title="Seeds that start now, and seeds that wait in the hx queue">
      {plan.now} now
      {plan.cvd.length > 0 ? (
        <>
          , <code>CUDA_VISIBLE_DEVICES={plan.cvd.join(",")}</code>
        </>
      ) : null}
      {plan.queued > 0 ? `, ${plan.queued} queued` : null}
      {plan.blocked > 0 ? <span className="bad">, {plan.blocked} won't start</span> : null}
    </span>
  );
}

function GpuRows({ host, draft, check, update }: RowProps & { host: LaunchHost }) {
  const plan = check.plan;
  return (
    <>
      <div className="fr">
        <span className="lb">GPUs</span>
        <div className="row">
          <Stepper label="GPUs per run" value={draft.gpus} max={gpuLimit(host)} onChange={(gpus) => update({ gpus })} />
          <span className="lbl-x">per run</span>
          {plan ? <GpuLine plan={plan} /> : null}
        </div>
      </div>
      {host.kind === "ssh" ? (
        <div className="fr">
          <span className="lb">Queue</span>
          <div className="row">
            <label className="sw">
              <input type="checkbox" checked={draft.queue} onChange={(e) => update({ queue: e.target.checked })} />
              <span className="tr" />
              wait for GPUs
            </label>
            {draft.queue && plan && plan.queued > 0 ? (
              <span className="small r" title={`Position in the ${host.name} queue after ${host.queue} waiting runs`}>
                {posRange(plan)}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  );
}

function SlurmRow({ draft, check, update }: RowProps) {
  const slurm = { partition: draft.partition, account: draft.account, time: draft.time };
  return (
    <div className="fr">
      <span className="lb" title="sbatch options; a blank field keeps the host's default from environments.yaml">
        SLURM
      </span>
      <div className="row">
        <span className="pair">
          <label className="lbl-x" htmlFor="hx-launch-part">
            partition
          </label>
          <input
            id="hx-launch-part"
            className="in mono w-m"
            value={draft.partition}
            placeholder="default"
            spellCheck={false}
            aria-invalid={check.partitionError ? true : undefined}
            onChange={(e) => update({ partition: e.target.value })}
          />
        </span>
        <span className="pair">
          <label className="lbl-x" htmlFor="hx-launch-time">
            time
          </label>
          <input
            id="hx-launch-time"
            className="in mono w-m"
            value={draft.time}
            placeholder="default"
            spellCheck={false}
            title="--time: h:mm:ss or d-hh:mm:ss; blank keeps the host's default"
            aria-invalid={check.timeError ? true : undefined}
            onChange={(e) => update({ time: e.target.value })}
          />
        </span>
        <span className="pair">
          <label className="lbl-x" htmlFor="hx-launch-acct">
            account
          </label>
          <input
            id="hx-launch-acct"
            className="in mono w-m"
            value={draft.account}
            placeholder="default"
            spellCheck={false}
            aria-invalid={check.accountError ? true : undefined}
            onChange={(e) => update({ account: e.target.value })}
          />
        </span>
        <span className="pair">
          <span className="lbl-x">gpus</span>
          <Stepper label="GPUs per job" value={draft.gpus} max={SLURM_MAX_GPUS} onChange={(gpus) => update({ gpus })} />
        </span>
        <code className="p sb" title="sbatch flags hx will use">
          {sbatchLine(slurm, draft.gpus)}
        </code>
        {[check.timeError, check.partitionError, check.accountError].map((err) =>
          err ? (
            <span key={err} className="small bad">
              {err}
            </span>
          ) : null,
        )}
      </div>
    </div>
  );
}

function CommandRow({ draft, check, update, where }: RowProps & { where: string }) {
  return (
    <div className="fr">
      <label htmlFor="hx-launch-cmd">Command</label>
      <div>
        <div className="tmpl" title={SEED_HINT}>
          <div className="tmpl-hl" aria-hidden="true" data-testid="template-highlight">
            {templateSegments(draft.command).map((s, i) =>
              s.seed ? (
                <mark key={i} className="tok" title={SEED_HINT}>
                  {s.text}
                </mark>
              ) : (
                <span key={i}>{s.text}</span>
              ),
            )}
            {"​"}
          </div>
          <textarea
            id="hx-launch-cmd"
            rows={1}
            spellCheck={false}
            autoComplete="off"
            value={draft.command}
            placeholder="python train.py --seed {seed}"
            aria-invalid={check.commandError ? true : undefined}
            onChange={(e) => update({ command: e.target.value })}
          />
        </div>
        {where ? <div className="lbl-x where">{where}</div> : null}
        {check.commandError ? <p className="small bad">command: {check.commandError}</p> : null}
        {check.warnings.map((w) => (
          <p key={w} className="small warn">
            {w}
          </p>
        ))}
      </div>
    </div>
  );
}

/** The first seed still to launch, as it will run (after a partial launch: the next one not started). */
function Preview({ host, check }: { host: LaunchHost | null; check: DraftCheck }) {
  const seed = check.pending[0];
  if (host === null || check.argv.length === 0 || seed === undefined) {
    return (
      <code className="cmd" aria-label="Preview">
        ·
      </code>
    );
  }
  const cvd =
    host.kind !== "slurm" && check.plan !== null && check.plan.cvd.length > 0
      ? `CUDA_VISIBLE_DEVICES=${check.plan.cvd.join(",")} `
      : "";
  return (
    <code className="cmd" aria-label="Preview" title={`Seed ${seed}, as it will run on ${host.name}`}>
      <span className="hostp">{host.name}:</span> {cvd}
      {templateSegments(shellJoin(check.argv)).map((s, i) =>
        s.seed ? (
          <b key={i} className="tok">
            {seed}
          </b>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </code>
  );
}

export function LaunchDialog({
  project,
  task,
  repo,
  commit = null,
  title = "New run",
  initial,
  carry = NO_CARRY,
  onClose,
  onLaunched,
}: LaunchDialogProps) {
  const client = useQueryClient();
  const hosts = useLaunchHosts();
  const [draft, setDraft] = useState<LaunchDraft>(() => ({ ...DEFAULT_DRAFT, ...initial }));
  const [attempt, setAttempt] = useState<string>(() => newCommandId());
  const [progress, setProgress] = useState<number | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [launched, setLaunched] = useState<Launched>(NOTHING_LAUNCHED);
  const [copy, setCopy] = useState<CopyState>("idle");
  const inFlight = useRef(false);
  const picked = useRef(false);

  useEffect(() => {
    if (picked.current || hosts.data === undefined) return;
    picked.current = true;
    const name = pickHost(hosts.data, project, draft.host);
    const chosen = hosts.data.find((h) => h.name === name);
    setDraft((d) => ({ ...d, host: name, gpus: chosen ? gpusForHost(d.gpus, chosen) : d.gpus }));
  }, [hosts.data, project, draft.host]);

  useEffect(() => {
    if (copy === "idle") return;
    const timer = setTimeout(() => setCopy("idle"), 1500);
    return () => clearTimeout(timer);
  }, [copy]);

  const now = Date.now();
  const host = hosts.data?.find((h) => h.name === draft.host) ?? null;
  // seeds this dialog started already are never sent again, even under a new attempt id, and
  // the GPU plan counts only the rest (the started seeds hold GPUs of their own by now)
  const check = checkDraft(draft, host, project, now, launched.seeds);
  const n = check.seeds.length;
  const pending = check.pending;
  const busy = progress !== null;
  const blocked = check.blockers.length > 0;
  const spec: LaunchSpec | null =
    host === null || check.argv.length === 0
      ? null
      : {
          host,
          project,
          repo,
          commit,
          task,
          argv: check.argv,
          hypothesis: draft.hypothesis,
          gpus: draft.gpus,
          queue: draft.queue,
          slurm: host.kind === "slurm" ? { partition: draft.partition, account: draft.account, time: draft.time } : null,
          params: carry.params,
          vars: carry.vars,
        };
  // the preview, Copy as CLI and the summary cover only the seeds Launch would send: after a
  // partial launch, pasting the started seeds' lines would start them a second time
  const cli = spec !== null && pending.length > 0 ? launchCli(spec, pending) : "";
  const pin = commit === null ? "" : ` @ ${commit.slice(0, 7)}`;
  const where = host === null ? "" : `${host.kind === "hub" ? repo : `${project} @ ${host.name}`}${pin}`;

  const update: Update = (patch) => {
    setDraft((d) => ({ ...d, ...patch }));
    setAttempt(newCommandId());
    setFailure(null);
  };

  const copyCli = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(cli);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  };

  const launch = async (): Promise<void> => {
    if (inFlight.current || spec === null || blocked || pending.length === 0) return;
    inFlight.current = true;
    setFailure(null);
    setProgress(0);
    const out = await launchSeeds(spec, pending, attempt, { onProgress: setProgress });
    inFlight.current = false;
    setProgress(null);
    for (const queryKey of REMOTE_RUN_INVALIDATES) void client.invalidateQueries({ queryKey });
    const done: Launched = {
      seeds: [...launched.seeds, ...pending.slice(0, out.records.length)],
      records: [...launched.records, ...out.records],
    };
    setLaunched(done);
    if (out.failed !== null) {
      setFailure({
        seed: out.failed.seed,
        message: out.failed.error.message,
        done: done.seeds.length,
        left: pending.length - out.records.length,
      });
      return;
    }
    onLaunched(done.records, spec.host.name);
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    if (e.key === "Escape" && !busy) {
      e.stopPropagation();
      onClose();
    }
  };
  const onBackdrop = (e: ReactMouseEvent<HTMLDivElement>): void => {
    if (e.target === e.currentTarget && !busy) onClose();
  };

  return (
    <div className="hx-launch" onKeyDown={onKeyDown} onMouseDown={onBackdrop}>
      <LaunchStyles />
      <div className="dlg" role="dialog" aria-modal="true" aria-labelledby="hx-launch-h">
        <div className="dlg-h">
          <h2 id="hx-launch-h">{title}</h2>
          <span className="small">{task ? `${project} / ${task}` : project}</span>
          <button type="button" className="x" aria-label="Close" disabled={busy} onClick={onClose}>
            ×
          </button>
        </div>
        <div className="dlg-b">
          <div className="fr">
            <span className="lb">Host</span>
            {hosts.error ? (
              <ErrorBox error={hosts.error} />
            ) : hosts.data === undefined ? (
              <Loading />
            ) : (
              <HostPicker
                hosts={hosts.data}
                selected={draft.host}
                project={project}
                now={now}
                onPick={(h) => update({ host: h.name, gpus: gpusForHost(draft.gpus, h) })}
              />
            )}
          </div>
          {host?.kind === "slurm" ? (
            <SlurmRow draft={draft} check={check} update={update} />
          ) : host !== null ? (
            <GpuRows host={host} draft={draft} check={check} update={update} />
          ) : null}
          <div className="fr">
            <label htmlFor="hx-launch-seeds">Seeds</label>
            <div className="row">
              <input
                id="hx-launch-seeds"
                className="in mono w-s"
                value={draft.seeds}
                spellCheck={false}
                title="Integers or ranges: 4, 5, 6 or 1-3"
                aria-invalid={check.seedsError ? true : undefined}
                onChange={(e) => update({ seeds: e.target.value })}
              />
              <span className="lbl-x">×{n}</span>
              {check.seedsError ? <span className="small bad">{check.seedsError}</span> : null}
            </div>
          </div>
          <CommandRow draft={draft} check={check} update={update} where={where} />
          <div className="fr">
            <label htmlFor="hx-launch-hyp">Hypothesis</label>
            <input
              id="hx-launch-hyp"
              className="in w-l"
              value={draft.hypothesis}
              placeholder="why this run exists"
              aria-required="true"
              autoFocus
              onChange={(e) => update({ hypothesis: e.target.value })}
            />
          </div>
          <div className="fr">
            <span className="lb">Preview</span>
            <div className="prev">
              <Preview host={host} check={check} />
              <span className="xn">×{pending.length}</span>
            </div>
          </div>
        </div>
        {failure ? (
          <p className="err" role="alert">
            seed {failure.seed}: {failure.message}. {failure.done} of {failure.done + failure.left} launched; Launch
            sends the other {failure.left}.
          </p>
        ) : null}
        <div className="dlg-f">
          <button
            type="button"
            className="btn"
            disabled={cli === ""}
            title={cli || "Needs a host, seeds and a command"}
            onClick={() => void copyCli()}
          >
            {COPY_TEXT[copy]}
          </button>
          <span className="sum small">
            {host !== null && pending.length > 0 ? launchSummary(host, draft.gpus, pending.length, draft.time) : ""}
          </span>
          <button type="button" className="btn" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || blocked || pending.length === 0}
            title={blocked ? check.blockers.join("; ") : `Launch ${pending.length} on ${host?.name ?? ""}`}
            onClick={() => void launch()}
          >
            {progress !== null ? `Launching ${progress}/${pending.length}` : `Launch ${pending.length}`}
          </button>
        </div>
      </div>
    </div>
  );
}

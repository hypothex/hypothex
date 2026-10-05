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
 * The form is locked while seeds are sent, and after a seed whose outcome is unknown (no
 * answer: it may have started): only a resend under the same id can settle that seed.
 * Resend sends that seed alone and skips the GPU plan, which counts it as not started
 * although it may hold its GPU already; the seeds after it wait for the form, unlocked
 * again once the seed is settled. A refused resend keeps the seed unknown: the first try
 * may still have started it.
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
import { auth } from "../api/auth";
import type { RunRecord } from "../api/models";
import { REMOTE_RUN_INVALIDATES } from "../api/queries";
import { ErrorBox, Loading } from "../pages/components/QueryState";
import { launchCli, sbatchLine } from "./cli";
import { SEED_HINT, previewSegments, templateSegments } from "./command";
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
  initialHost,
  initialGpus,
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
  /** Resolve a template's environment without substituting another available host. */
  templateEnvironment?: string;
  /** Params and vars of the template run, sent with every seed. */
  carry?: Carry;
  /** A note next to the seeds, e.g. why none is proposed (`LaunchDefaults.seedsNote`). */
  seedsNote?: string;
  onClose: () => void;
  /** Confirmed runs, once on completion or partial close; never an unanswered seed. */
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
  /** The seed may have started: the form stays locked until a resend settles it. */
  unknown: boolean;
  /** Seeds started by this dialog so far, and seeds still to send. */
  done: number;
  left: number;
}

/** Seeds this dialog has started, in launch order, with their records and the host they run on. */
interface Launched {
  host: string | null;
  seeds: number[];
  records: RunRecord[];
}

const NOTHING_LAUNCHED: Launched = { host: null, seeds: [], records: [] };

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
  lockedTo,
  onPick,
}: {
  hosts: LaunchHost[];
  selected: string | null;
  project: string;
  now: number;
  /** after a partial launch the rest of the seeds go to the same host: the others are disabled */
  lockedTo: string | null;
  onPick: (host: LaunchHost) => void;
}) {
  return (
    <div className="hp" role="radiogroup" aria-label="Host">
      {hosts.map((h) => {
        const av = availability(h, project, now);
        const locked = lockedTo !== null && h.name !== lockedTo;
        const ok = av.ok && !locked;
        const on = h.name === selected;
        const cls = [on ? "on" : "", ok ? "" : "off"].filter(Boolean).join(" ");
        const title = locked ? `seeds started on ${lockedTo}: the rest go there` : av.ok ? hostTitle(h) : av.reason;
        return (
          <label key={h.name} className={cls || undefined} title={title}>
            <input
              type="radio"
              name="hx-launch-host"
              value={h.name}
              aria-label={h.name}
              checked={on}
              disabled={!ok}
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
            <label className="hx-sw">
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
function Preview({ host, check, vars }: { host: LaunchHost | null; check: DraftCheck; vars: Carry["vars"] }) {
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
      {previewSegments(check.argv, vars, seed).map((s, i) =>
        s.seed ? (
          <b key={i} className="tok">
            {s.text}
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
  templateEnvironment,
  carry = NO_CARRY,
  seedsNote,
  onClose,
  onLaunched,
}: LaunchDialogProps) {
  const client = useQueryClient();
  const hosts = useLaunchHosts();
  const [draft, setDraft] = useState<LaunchDraft>(() => ({ ...DEFAULT_DRAFT, ...initial }));
  const [attempt, setAttempt] = useState<string>(() => newCommandId());
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [launched, setLaunched] = useState<Launched>(NOTHING_LAUNCHED);
  const [copy, setCopy] = useState<CopyState>("idle");
  const inFlight = useRef(false);
  const picked = useRef(false);
  const reported = useRef(false);
  const launchedGeneration = useRef<number | null>(null);

  useEffect(() => {
    if (picked.current || hosts.data === undefined) return;
    picked.current = true;
    const name = initialHost(hosts.data, project, draft.host, templateEnvironment);
    const chosen = hosts.data.find((h) => h.name === name);
    setDraft((d) => ({ ...d, host: name, gpus: chosen ? initialGpus(chosen, initial?.gpus) : d.gpus }));
  }, [hosts.data, project, draft.host, templateEnvironment, initial?.gpus]);

  useEffect(() => {
    if (copy === "idle") return;
    const timer = setTimeout(() => setCopy("idle"), 1500);
    return () => clearTimeout(timer);
  }, [copy]);

  const now = Date.now();
  const host = hosts.data?.find((h) => h.name === draft.host) ?? null;
  // seeds this dialog started already are never sent again, even under a new attempt id, and
  // the GPU plan counts only the rest (the started seeds hold GPUs of their own by now)
  const check = checkDraft(draft, host, project, now, launched.seeds, carry.vars);
  const n = check.seeds.length;
  const pending = check.pending;
  const busy = progress !== null;
  // an edit gives every seed a new command id: never while seeds are sent, nor while a seed
  // that may have started waits for its resend
  const locked = busy || failure?.unknown === true;
  // the seed that may have started: the only one Launch (as Resend) sends until it is settled
  const resend = failure?.unknown === true ? failure.seed : null;
  // the started seeds and the rest must share one host: onLaunched names a single host
  const blockers =
    launched.host !== null && draft.host !== launched.host
      ? [...check.blockers, `seeds started on ${launched.host}: the rest go there`]
      : check.blockers;
  const blocked = blockers.length > 0;
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
    if (inFlight.current || locked) return;
    setDraft((d) => ({ ...d, ...patch }));
    setAttempt(newCommandId());
    setFailure(null);
  };

  const reportLaunched = (done: Launched): void => {
    if (reported.current || done.host === null || done.records.length === 0) return;
    if (launchedGeneration.current === null || !auth.current(launchedGeneration.current)) return;
    reported.current = true;
    onLaunched(done.records, done.host);
  };

  const close = (): void => {
    if (inFlight.current) return;
    reportLaunched(launched);
    onClose();
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
    if (inFlight.current || spec === null) return;
    if (resend === null && (blocked || pending.length === 0)) return;
    const generation = auth.snapshot().generation;
    const toSend = resend === null ? pending : [resend];
    inFlight.current = true;
    setFailure(null);
    setProgress({ done: 0, total: toSend.length });
    const out = await launchSeeds(spec, toSend, attempt, {
      onProgress: (n) => {
        if (auth.current(generation)) setProgress({ done: n, total: toSend.length });
      },
    });
    if (!auth.current(generation)) return;
    launchedGeneration.current = generation;
    inFlight.current = false;
    setProgress(null);
    for (const queryKey of REMOTE_RUN_INVALIDATES) void client.invalidateQueries({ queryKey });
    const seeds = [...launched.seeds, ...toSend.slice(0, out.records.length)];
    const done: Launched = {
      // lock the host only once a seed runs there: if none started, the user may pick another host
      host: seeds.length > 0 ? spec.host.name : null,
      seeds,
      records: [...launched.records, ...out.records],
    };
    setLaunched(done);
    const left = pending.filter((seed) => !seeds.includes(seed)).length;
    if (out.failed !== null) {
      setFailure({
        seed: out.failed.seed,
        message: out.failed.error.message,
        // a refused resend answers only the resend: the first try may still have started it
        unknown: out.failed.unknown || out.failed.seed === resend,
        done: done.seeds.length,
        left,
      });
      return;
    }
    if (left === 0) reportLaunched(done);
  };

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    if (e.key === "Escape" && !busy) {
      e.stopPropagation();
      close();
    }
  };
  const onBackdrop = (e: ReactMouseEvent<HTMLDivElement>): void => {
    if (e.target === e.currentTarget && !busy) close();
  };

  return (
    <div className="hx-launch" onKeyDown={onKeyDown} onMouseDown={onBackdrop}>
      <LaunchStyles />
      <div className="dlg" role="dialog" aria-modal="true" aria-labelledby="hx-launch-h">
        <div className="dlg-h">
          <h2 id="hx-launch-h">{title}</h2>
          <span className="small">{task ? `${project} / ${task}` : project}</span>
          <button type="button" className="x" aria-label="Close" disabled={busy} onClick={close}>
            ×
          </button>
        </div>
        <fieldset className="dlg-b" disabled={locked}>
          <div className="fr">
            <span className="lb">Host</span>
            <div>
              {hosts.error ? <ErrorBox error={hosts.error} /> : null}
              {hosts.data !== undefined ? (
                <HostPicker
                  hosts={hosts.data}
                  selected={draft.host}
                  project={project}
                  now={now}
                  lockedTo={launched.host}
                  onPick={(h) => update({ host: h.name, gpus: h.slurm?.defaults?.gpus ?? gpusForHost(draft.gpus, h, host) })}
                />
              ) : hosts.error ? null : <Loading />}
            </div>
          </div>
          {templateEnvironment && draft.host === null && hosts.data ? (
            <p className="small warn">
              Template environment {templateEnvironment} has no configured host; pick a host explicitly.
            </p>
          ) : null}
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
              {seedsNote ? <span className="small warn">{seedsNote}</span> : null}
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
              <Preview host={host} check={check} vars={carry.vars} />
              <span className="xn">×{pending.length}</span>
            </div>
          </div>
        </fieldset>
        {failure ? (
          <p className="err" role="alert">
            seed {failure.seed}: {failure.message}. {failure.done} of {failure.done + failure.left} launched;{" "}
            {failure.unknown
              ? `seed ${failure.seed} may have started: the form is locked; Resend seed ${failure.seed} sends it again under the same id.`
              : `Launch sends the other ${failure.left}.`}
          </p>
        ) : null}
        <div className="dlg-f">
          <button
            type="button"
            className="btn"
            disabled={cli === "" || locked}
            title={cli || "Needs a host, seeds and a command"}
            onClick={() => void copyCli()}
          >
            {COPY_TEXT[copy]}
          </button>
          <span className="sum small">
            {host !== null && pending.length > 0 ? launchSummary(host, draft.gpus, pending.length, draft.time) : ""}
          </span>
          <button type="button" className="btn" disabled={busy} onClick={close}>
            Cancel
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={busy || (resend === null ? blocked || pending.length === 0 : spec === null)}
            title={
              resend !== null
                ? `Send seed ${resend} again under the same id`
                : blocked
                  ? blockers.join("; ")
                  : `Launch ${pending.length} on ${host?.name ?? ""}`
            }
            onClick={() => void launch()}
          >
            {progress !== null
              ? `Launching ${progress.done}/${progress.total}`
              : resend !== null
                ? `Resend seed ${resend}`
                : `Launch ${pending.length}`}
          </button>
        </div>
      </div>
    </div>
  );
}

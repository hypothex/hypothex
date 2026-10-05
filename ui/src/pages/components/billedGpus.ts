import type { RunRecord } from "../../api/models";

/**
 * GPUs a run is billed for, as the backend's `billed_gpus`: the GPUs it holds; a SLURM run
 * whose node reported no indices, the GPUs it asked for (SLURM reserved that many).
 */
export function billedGpus(record: RunRecord): number {
  const held = (record.executor.gpus ?? []).length;
  if (held > 0) return held;
  return record.executor.slurm_job_id ? (record.gpus_requested ?? 0) : 0;
}


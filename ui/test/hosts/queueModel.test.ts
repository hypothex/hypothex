import { expect, test } from "bun:test";
import { queueGroups } from "../../src/hosts/queueModel";
import { HOSTS } from "../api/phase2-fixtures";
import { NOW, pendingRecord, queuedRecord } from "../pages/remoteFixtures";

test("queued runs grouped by the host that serves their environment, in queue order", () => {
  const first = queuedRecord({ run_id: "q1", executor: { ...queuedRecord().executor, queue_position: 1 } });
  const groups = queueGroups([queuedRecord(), pendingRecord(), first], HOSTS, NOW);
  expect(groups.map((g) => [g.host, g.rows.map((r) => r.runId)])).toEqual([
    ["gpu1", ["q1", queuedRecord().run_id]],
    ["mccleary", [pendingRecord().run_id]],
  ]);
  expect(groups[0]?.row?.name).toBe("gpu1");
  expect(groups[0]?.rows[0]?.record.run_id).toBe("q1");
});

test("without the hosts list a group is named by the machine's hostname", () => {
  expect(queueGroups([queuedRecord()], undefined, NOW)[0]?.host).toBe("sv-a100-01");
});

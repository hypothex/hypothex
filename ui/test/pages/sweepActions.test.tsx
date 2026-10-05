import { afterEach, describe, expect, test } from "bun:test";
import { QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import type { SweepIssuance } from "../../src/api/models";
import { useSweep } from "../../src/api/queries";
import { SweepActions } from "../../src/pages/components/SweepActions";
import { sweepCli } from "../../src/pages/components/SweepModel";
import { HttpReply, mockApi, mockClipboard, renderWithClient, restoreFetch } from "./helpers";
import { PROJECT, RUNS, SWEEP_ID, makeSummary } from "./sweepFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const SPEC = makeSummary().spec;
const BASE = `/api/v1/sweeps/${PROJECT}/${SWEEP_ID}`;
const incompleteIssuance = (state: "incomplete" | "interrupted"): SweepIssuance => ({ state, episode: 1, revision: 3, planned: 8, accepted_at: "now", updated_at: "now", cancel_requested: false, reason: "worker_lost", error: null, resume: { seeds: [2, 7], message: "Resume missing cells" } });

test("a sweep with over twenty seeds opens with a valid bounded count", () => {
  renderWithClient(<SweepActions project={PROJECT} sweepId={SWEEP_ID} spec={{ ...SPEC, seeds: Array.from({ length: 21 }, (_, i) => i + 1) }} queued={0} cellCount={1} runs={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
  expect((screen.getByLabelText("New seeds per cell") as HTMLInputElement).value).toBe("20");
  expect(screen.getByRole("button", { name: "Add 20 runs" }).hasAttribute("disabled")).toBe(false);
});

test("closing Add seeds clears its old error, and a disabled cancel error can be dismissed", async () => {
  mockApi({
    [`POST ${BASE}/extend`]: new HttpReply(400, { error: "cannot extend", type: "SweepError" }),
    [`POST ${BASE}/cancel_queued`]: new HttpReply(400, { error: "cannot cancel", type: "SweepError" }),
  });
  const tree = (queued: number) => <SweepActions project={PROJECT} sweepId={SWEEP_ID} spec={SPEC} queued={queued} cellCount={4} runs={RUNS} />;
  const { client, rerender } = renderWithClient(tree(1));
  fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
  fireEvent.click(screen.getByRole("button", { name: "Add 8 runs" }));
  await screen.findByText("cannot extend");
  fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
  await waitFor(() => expect(screen.queryByRole("alert") === null).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: "Cancel queued" }));
  await screen.findByText("cannot cancel");
  rerender(<QueryClientProvider client={client}>{tree(0)}</QueryClientProvider>);
  expect(screen.getByRole("button", { name: "Cancel queued" }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Dismiss cancel error" }));
  await waitFor(() => expect(screen.queryByRole("alert") === null).toBe(true));
});

for (const state of ["incomplete", "interrupted"] as const) {
  test(`${state} with no observed queue allows Cancel and Resume, unless cancellation already requested`, () => {
    mockApi({});
    const issuance = incompleteIssuance(state);
    const tree = (current: SweepIssuance) => <SweepActions project={PROJECT} sweepId={SWEEP_ID} spec={SPEC} queued={0} cellCount={4} runs={[]} issuance={current} />;
    const { client, rerender } = renderWithClient(tree(issuance));
    expect(screen.getByRole("button", { name: "Cancel queued" }).hasAttribute("disabled")).toBe(false);
    expect(screen.getByRole("button", { name: "Resume" }).hasAttribute("disabled")).toBe(false);
    for (const current of [{ ...issuance, cancel_requested: true }, { ...issuance, reason: "cancelled" as const }]) {
      rerender(<QueryClientProvider client={client}>{tree(current)}</QueryClientProvider>);
      expect(screen.getByRole("button", { name: "Cancel queued" }).hasAttribute("disabled")).toBe(true);
    }
  });
}

test("cancelling unobserved accepted members refetches settling, blocks Resume and polls until terminal cancellation", async () => {
  let issuance = incompleteIssuance("incomplete");
  let settlingReads = 0;
  const calls = mockApi({
    [`GET ${BASE}`]: () => {
      if (issuance.state === "settling" && ++settlingReads > 1) issuance = { ...issuance, state: "interrupted", reason: "cancelled", resume: null };
      return { ...makeSummary(), issuance };
    },
    [`POST ${BASE}/cancel_queued`]: () => {
      issuance = { ...issuance, state: "settling", cancel_requested: true };
      return { ...makeSummary(), issuance };
    },
  });
  function LiveActions() {
    const summary = useSweep(PROJECT, SWEEP_ID).data;
    return summary ? <><output data-testid="issuance-state">{summary.issuance?.state}:{String(summary.issuance?.cancel_requested)}</output><SweepActions project={PROJECT} sweepId={SWEEP_ID} spec={summary.spec} queued={0} cellCount={4} runs={[]} issuance={summary.issuance} /></> : null;
  }
  const { client, unmount } = renderWithClient(<LiveActions />);
  await screen.findByRole("button", { name: "Resume" });
  fireEvent.click(screen.getByRole("button", { name: "Cancel queued" }));
  await waitFor(() => expect(screen.getByTestId("issuance-state").textContent).toBe("settling:true"));
  expect(screen.getByRole("button", { name: "Resume" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: "Add seeds" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: "Cancel queued" }).hasAttribute("disabled")).toBe(true);
  await waitFor(() => expect(screen.getByTestId("issuance-state").textContent).toBe("interrupted:true"), { timeout: 4500 });
  const reads = calls.filter((call) => call.method === "GET").length;
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 2200)); });
  expect(calls.filter((call) => call.method === "GET")).toHaveLength(reads);
  expect(calls.filter((call) => call.method === "POST")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "Resume" }) === null).toBe(true);
  expect(screen.getByRole("button", { name: "Cancel queued" }).hasAttribute("disabled")).toBe(true);
  unmount();
  client.clear();
}, 8000);

function renderActions(queued = 1) {
  return renderWithClient(
    <SweepActions project={PROJECT} sweepId={SWEEP_ID} spec={SPEC} queued={queued} cellCount={4} runs={RUNS} />,
  );
}

const seedInput = (): HTMLInputElement =>
  screen.getByRole("spinbutton", { name: "New seeds per cell" }) as HTMLInputElement;

describe("SweepActions", () => {
  test("Copy as CLI copies the hx sweep command", async () => {
    const written = mockClipboard();
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Copy as CLI" }));
    await screen.findByRole("button", { name: "Copied" });
    expect(written).toEqual([sweepCli(SPEC, RUNS)]);
    expect(written[0]).toStartWith("hx sweep -t fwd --grid lr=1e-4,3e-4");
  });

  test("a blocked clipboard says so", async () => {
    mockClipboard(true);
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Copy as CLI" }));
    expect(await screen.findByRole("button", { name: "Clipboard blocked" })).toBeTruthy();
  });

  test("Cancel queued is off with nothing queued", () => {
    mockApi({});
    renderActions(0);
    const cancel = screen.getByRole("button", { name: "Cancel queued" });
    expect(cancel.hasAttribute("disabled")).toBe(true);
    expect(cancel.getAttribute("title")).toBe("No queued runs");
  });

  test("Cancel queued posts once with a command id", async () => {
    const calls = mockApi({ [`POST ${BASE}/cancel_queued`]: makeSummary() });
    renderActions(3);
    const cancel = screen.getByRole("button", { name: "Cancel queued" });
    expect(cancel.getAttribute("title")).toBe("Cancel the 3 queued runs");
    fireEvent.click(cancel);
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]?.method).toBe("POST");
    expect(calls[0]?.url).toBe(`${BASE}/cancel_queued`);
    expect(typeof (calls[0]?.body as { command_id?: unknown }).command_id).toBe("string");
  });

  test("Add seeds adds the next seeds to every cell", async () => {
    const calls = mockApi({ [`POST ${BASE}/extend`]: makeSummary() });
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    expect(seedInput().value).toBe("2");
    expect(screen.getByText("3, 4 × 4 cells = 8 runs")).toBeTruthy();
    fireEvent.change(seedInput(), { target: { value: "1" } });
    expect(screen.getByText("3 × 4 cells = 4 runs")).toBeTruthy();
    fireEvent.change(seedInput(), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Add 8 runs" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]?.url).toBe(`${BASE}/extend`);
    expect(calls[0]?.body).toMatchObject({ seeds: [3, 4] });
    expect(typeof (calls[0]?.body as { command_id?: unknown }).command_id).toBe("string");
    await waitFor(() => expect(screen.queryByRole("form", { name: "Add seeds" })).toBeNull());
  });

  test("an invalid seed count disables Add", () => {
    mockApi({});
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    fireEvent.change(seedInput(), { target: { value: "0" } });
    expect(screen.getByRole("button", { name: "Add 0 runs" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("1–20")).toBeTruthy();
  });

  test("a refused extend shows the server's reason", async () => {
    mockApi({
      [`POST ${BASE}/extend`]: new HttpReply(400, {
        error: "sweep would launch 1008 runs; the limit is 1000",
        type: "SweepError",
      }),
    });
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    fireEvent.click(screen.getByRole("button", { name: "Add 8 runs" }));
    expect((await screen.findByRole("alert")).textContent).toBe("sweep would launch 1008 runs; the limit is 1000");
  });

  test("a lost answer resends the same extend; the hub issues only the missing runs", async () => {
    // seeds already in the sweep are fine on the hub (`extend_sweep` resumes a cut extend),
    // so the resend under the same command id may repeat the seeds
    let tries = 0;
    const calls = mockApi({
      [`POST ${BASE}/extend`]: () => {
        tries += 1;
        if (tries === 1) throw new TypeError("connection reset");
        return makeSummary();
      },
    });
    renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    fireEvent.click(screen.getByRole("button", { name: "Add 8 runs" }));
    await waitFor(() => expect(tries).toBe(2));
    await waitFor(() => expect(screen.queryByRole("form", { name: "Add seeds" })).toBeNull());
    const sent = calls.filter((c) => c.url === `${BASE}/extend`);
    expect(sent).toHaveLength(2);
    expect(sent.map((c) => (c.body as { seeds: number[] }).seeds)).toEqual([
      [3, 4],
      [3, 4],
    ]);
    const ids = sent.map((c) => (c.body as { command_id: string }).command_id);
    expect(ids[0]).toBe(ids[1] as string);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("a failed extend keeps its seeds: after the summary shows them saved, the retry sends them again, not the next ones", async () => {
    // the hub saves seeds 3, 4 in the sweep before it issues their runs; then a host fails
    let fail = true;
    const calls = mockApi({
      [`POST ${BASE}/extend`]: () => {
        if (fail) {
          fail = false;
          return new HttpReply(503, { error: "gpu1 is not connected", type: "HostUnavailableError" });
        }
        return makeSummary();
      },
    });
    const { client, rerender } = renderActions();
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    fireEvent.click(screen.getByRole("button", { name: "Add 8 runs" }));
    expect((await screen.findByRole("alert")).textContent).toBe("gpu1 is not connected");
    // the summary refetch now lists seeds 1-4
    const saved = { ...SPEC, seeds: [1, 2, 3, 4] };
    rerender(
      <QueryClientProvider client={client}>
        <SweepActions project={PROJECT} sweepId={SWEEP_ID} spec={saved} queued={1} cellCount={4} runs={RUNS} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("3, 4 × 4 cells = 8 runs")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add 8 runs" }));
    await waitFor(() => expect(calls.filter((c) => c.url === `${BASE}/extend`)).toHaveLength(2));
    const sent = calls.filter((c) => c.url === `${BASE}/extend`);
    expect(sent.map((c) => (c.body as { seeds: number[] }).seeds)).toEqual([
      [3, 4],
      [3, 4],
    ]);
    await waitFor(() => expect(screen.queryByRole("form", { name: "Add seeds" })).toBeNull());
    // once it went through, the next Add seeds proposes the seeds after them
    fireEvent.click(screen.getByRole("button", { name: "Add seeds" }));
    expect(screen.getByText("5, 6 × 4 cells = 8 runs")).toBeTruthy();
  });
});

test("active issuance with zero mirrored runs remains cancellable and blocks extension", async () => {
  const calls = mockApi({ [`POST ${BASE}/cancel_queued`]: makeSummary() });
  const issuance = { state: "issuing" as const, episode: 1, revision: 2, planned: 8, accepted_at: "now", updated_at: "now", cancel_requested: false, reason: null, error: null, resume: null };
  renderWithClient(<SweepActions project={PROJECT} sweepId={SWEEP_ID} spec={SPEC} queued={0} cellCount={4} runs={[]} issuance={issuance} />);
  expect(screen.getByRole("button", { name: "Add seeds" }).hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Cancel queued" }));
  await waitFor(() => expect(calls).toHaveLength(1));
});
test("explicit Resume sends the server's exact missing seeds", async () => {
  const calls = mockApi({ [`POST ${BASE}/extend`]: makeSummary() });
  const issuance = { state: "interrupted" as const, episode: 1, revision: 3, planned: 8, accepted_at: "now", updated_at: "now", cancel_requested: false, reason: "worker_lost" as const, error: null, resume: { seeds: [2, 7], message: "Resume missing cells" } };
  renderWithClient(<SweepActions project={PROJECT} sweepId={SWEEP_ID} spec={SPEC} queued={0} cellCount={4} runs={[]} issuance={issuance} />);
  fireEvent.click(screen.getByRole("button", { name: "Resume" }));
  await waitFor(() => expect(calls[0]?.body).toMatchObject({ seeds: [2, 7] }));
});

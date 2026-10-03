import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
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
});

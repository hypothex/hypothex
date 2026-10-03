import { afterEach, expect, mock, test } from "bun:test";
import { useQuery } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { ApiError, api } from "../../src/api/client";
import { shouldRetry, useAction } from "../../src/pages/components/useAction";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

function Probe({ onDone }: { onDone: (d: { run_id: string }) => void }) {
  const action = useAction<{ run_id: string }>({ send: (_arg, opts) => api.rerun("R", opts), onSuccess: onDone });
  return (
    <div>
      <button type="button" onClick={() => action.run()} disabled={action.pending}>
        go
      </button>
      {action.error ? <p role="alert">{action.error.message}</p> : null}
    </div>
  );
}

test("shouldRetry retries unanswered requests twice and never HTTP errors", () => {
  const net = new TypeError("fetch failed");
  const offline = new ApiError(0, "Cannot reach hx serve", "NetworkError", [], null);
  expect(shouldRetry(0, net)).toBe(true);
  expect(shouldRetry(1, offline)).toBe(true);
  expect(shouldRetry(2, offline)).toBe(false);
  expect(shouldRetry(0, new ApiError(400, "bad", "RunError", [], null))).toBe(false);
});

test("retries a network failure with the same command_id", async () => {
  let attempts = 0;
  const calls = mockApi({
    "POST /api/v1/runs/R/rerun": () => {
      attempts += 1;
      if (attempts === 1) throw new TypeError("connection reset");
      return { run_id: "NEW" };
    },
  });
  const onDone = mock((_d: { run_id: string }) => {});
  renderWithClient(<Probe onDone={onDone} />);
  const button = screen.getByRole("button", { name: "go" });
  fireEvent.click(button);
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(true));
  await waitFor(() => expect(onDone).toHaveBeenCalledWith({ run_id: "NEW" }));
  expect(calls).toHaveLength(2);
  const [first, second] = calls.map((c) => c.body as Record<string, unknown>);
  expect(typeof first?.command_id).toBe("string");
  expect(second?.command_id).toBe(first?.command_id);
  expect(first?.created_by).toBe("human");
});

test("shows the server error and does not retry it", async () => {
  const calls = mockApi({
    "POST /api/v1/runs/R/rerun": new HttpReply(400, { error: "run is not active", type: "RunError" }),
  });
  renderWithClient(<Probe onDone={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "go" }));
  expect((await screen.findByRole("alert")).textContent).toBe("run is not active");
  expect(calls).toHaveLength(1);
});

test("two clicks send two different command_ids", async () => {
  const calls = mockApi({ "POST /api/v1/runs/R/rerun": { run_id: "NEW" } });
  const onDone = mock((_d: { run_id: string }) => {});
  renderWithClient(<Probe onDone={onDone} />);
  const button = screen.getByRole("button", { name: "go" });
  fireEvent.click(button);
  await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
  fireEvent.click(button);
  await waitFor(() => expect(onDone).toHaveBeenCalledTimes(2));
  const ids = calls.map((c) => (c.body as { command_id: string }).command_id);
  expect(new Set(ids).size).toBe(2);
});

function SlowRefresh({ onDone }: { onDone: (d: { run_id: string }) => void }) {
  const run = useQuery({ queryKey: ["run", "R"], queryFn: ({ signal }) => api.run("R", signal) });
  const action = useAction<{ run_id: string }>({
    send: (_arg, opts) => api.rerun("R", opts),
    invalidate: [["run", "R"]],
    onSuccess: onDone,
  });
  return (
    <button type="button" onClick={() => action.run()} disabled={action.pending || run.isPending}>
      go
    </button>
  );
}

test("calls onSuccess and clears pending without waiting for the invalidated queries", async () => {
  let loads = 0;
  mockApi({
    "GET /api/v1/runs/R": () => {
      loads += 1;
      // The first load answers; the refetch after the action never does.
      return loads === 1 ? { run_id: "R" } : new Promise(() => {});
    },
    "POST /api/v1/runs/R/rerun": { run_id: "NEW" },
  });
  const onDone = mock((_d: { run_id: string }) => {});
  renderWithClient(<SlowRefresh onDone={onDone} />);
  const button = screen.getByRole("button", { name: "go" });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  fireEvent.click(button);
  await waitFor(() => expect(loads).toBe(2));
  await waitFor(() => expect(onDone).toHaveBeenCalledWith({ run_id: "NEW" }));
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
});

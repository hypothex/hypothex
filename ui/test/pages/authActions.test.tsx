import { afterEach, expect, mock, spyOn, test } from "bun:test";
import { QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { auth } from "../../src/api/auth";
import { AuthGate } from "../../src/api/AuthGate";
import { api } from "../../src/api/client";
import { createQueryClient } from "../../src/api/queries";
import { useAction } from "../../src/pages/components/useAction";
import { LaunchDialog } from "../../src/launch/LaunchDialog";
import { CMD, GPU1, PROJECT, REPO_PATH, TASK } from "../launch/fixtures";
import { makeRecord } from "./fixtures";
import { mockApi } from "./helpers";

const originalFetch = globalThis.fetch;
afterEach(() => {
  cleanup();
  globalThis.fetch = originalFetch;
  auth.select(null);
  sessionStorage.clear();
});

function Probe({ onDone }: { onDone: (value: { run_id: string }) => void }) {
  const action = useAction({ send: (_: void, opts) => api.rerun("R", opts), onSuccess: onDone });
  return <button onClick={() => action.run()}>Rerun probe</button>;
}

test("an action interrupted by a credential change never retries with the next credential", async () => {
  auth.select("old-synthetic");
  let resolveFirst!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { resolveFirst = resolve; });
  const posts: string[] = [];
  globalThis.fetch = (async (_url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method !== "POST") return new Response("[]");
    posts.push(new Headers(init.headers).get("Authorization") ?? "");
    return posts.length === 1 ? pending : new Response('{"run_id":"NEW"}');
  }) as typeof fetch;
  const client = createQueryClient();
  const onDone = mock((_value: { run_id: string }) => {});
  render(<QueryClientProvider client={client}><AuthGate><Probe onDone={onDone} /></AuthGate></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Rerun probe" }));
  await waitFor(() => expect(posts).toHaveLength(1));
  await act(async () => {
    const generation = auth.select("new-synthetic");
    auth.accept(generation);
    resolveFirst(new Response('{"run_id":"OLD"}'));
    await new Promise((resolve) => setTimeout(resolve, 700));
  });
  expect(posts).toHaveLength(1);
  expect(onDone).not.toHaveBeenCalled();
  client.clear();
});

test("a scheduled network retry cannot send after its credential generation is replaced", async () => {
  auth.select("old-synthetic");
  let posts = 0;
  globalThis.fetch = (async (_url: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method !== "POST") return new Response("[]");
    posts += 1;
    if (posts === 1) throw new TypeError("connection reset");
    return new Response('{"run_id":"NEW"}');
  }) as typeof fetch;
  const client = createQueryClient();
  const onDone = mock((_value: { run_id: string }) => {});
  render(<QueryClientProvider client={client}><AuthGate><Probe onDone={onDone} /></AuthGate></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Rerun probe" }));
  await waitFor(() => expect(posts).toBe(1));
  await act(async () => {
    const generation = auth.select("new-synthetic");
    auth.accept(generation);
    await new Promise((resolve) => setTimeout(resolve, 700));
  });
  expect(posts).toBe(1);
  expect(onDone).not.toHaveBeenCalled();
  client.clear();
});

test("a superseded launch dialog never invalidates the replacement session", async () => {
  auth.select("old-synthetic");
  let resolveFirst!: (value: unknown) => void;
  const pending = new Promise((resolve) => { resolveFirst = resolve; });
  const calls = mockApi({
    "GET /api/v1/projects": [],
    "GET /api/v1/hosts": [GPU1],
    "GET /api/v1/gpus": [],
    "GET /api/v1/queue": [],
    "POST /api/v1/hosts/gpu1/runs": () => pending,
  });
  const client = createQueryClient();
  const onLaunched = mock(() => {});
  render(<QueryClientProvider client={client}><AuthGate><LaunchDialog
    project={PROJECT} task={TASK} repo={REPO_PATH}
    initial={{ host: "gpu1", command: CMD, seeds: "1", gpus: 0, hypothesis: "credential test" }}
    onClose={() => {}} onLaunched={onLaunched}
  /></AuthGate></QueryClientProvider>);
  const button = await screen.findByRole("button", { name: "Launch 1" });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  fireEvent.click(button);
  await waitFor(() => expect(calls.filter((call) => call.method === "POST")).toHaveLength(1));
  const invalidate = spyOn(client, "invalidateQueries");
  await act(async () => { auth.lock(auth.snapshot().generation); });
  await screen.findByLabelText("Token");
  await act(async () => { auth.accept(auth.select("new-synthetic")); });
  await screen.findByRole("button", { name: "Launch 1" });
  await act(async () => {
    resolveFirst(makeRecord({ seed: 1 }));
    await new Promise((resolve) => setTimeout(resolve, 100));
  });
  expect(invalidate).not.toHaveBeenCalled();
  expect(onLaunched).not.toHaveBeenCalled();
  invalidate.mockRestore();
  client.clear();
});

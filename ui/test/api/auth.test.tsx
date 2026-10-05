import { afterEach, expect, test } from "bun:test";
import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { AuthStore, auth, TOKEN_KEY } from "../../src/api/auth";
import { AuthGate } from "../../src/api/AuthGate";
import { api, ApiError } from "../../src/api/client";
import { createQueryClient } from "../../src/api/queries";
const original = globalThis.fetch;
afterEach(async () => { globalThis.fetch = original; await act(async () => { auth.select(null); }); sessionStorage.clear(); });
const response = (status = 200) => new Response(status === 200 ? "[]" : '{"detail":"unauthorized"}', { status });
function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
test("optional storage failures keep credentials usable in memory", () => {
  const fail = () => { throw new Error("denied"); };
  const store = new AuthStore({ getItem: fail, setItem: fail, removeItem: fail });
  const generation = store.select("synthetic-root"); store.accept(generation);
  expect(store.snapshot().status).toBe("unlocked");
  expect(store.capture().token).toBe("synthetic-root");
  store.lock(generation); expect(store.capture().token).toBeNull();
});
test("bearer goes in HTTP headers, never URL; 403/404 preserve auth", async () => {
  const generation = auth.select("synthetic-root"); auth.accept(generation);
  for (const status of [200, 403, 404]) {
    globalThis.fetch = (async (url: RequestInfo | URL, init?: RequestInit) => {
      expect(String(url)).not.toContain("synthetic-root");
      expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer synthetic-root");
      return response(status);
    }) as unknown as typeof fetch;
    if (status === 200) await api.projects();
    else await expect(api.projects()).rejects.toBeInstanceOf(ApiError);
    expect(auth.snapshot().status).toBe("unlocked");
  }
});
test("401 clears credentials; stale 200 and 401 cannot affect a new credential", async () => {
  for (const status of [200, 401]) {
    auth.select("old-synthetic");
    const pending = deferred<Response>();
    globalThis.fetch = (() => pending.promise) as unknown as typeof fetch;
    const old = api.projects().catch((error: Error) => error);
    const signal = auth.capture().signal;
    const current = auth.select("new-synthetic"); auth.accept(current);
    expect(signal.aborted).toBe(true);
    pending.resolve(response(status));
    expect((await old as Error).name).toBe("AbortError");
    expect(auth.snapshot().status).toBe("unlocked");
  }
  globalThis.fetch = (async () => response(401)) as unknown as typeof fetch;
  await expect(api.projects()).rejects.toBeInstanceOf(ApiError);
  expect(auth.capture().token).toBeNull(); expect(auth.snapshot().status).toBe("locked");
  expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
});
test("gate waits for protected validation, supports noauth, clears cache/replay on lock", async () => {
  auth.select(null);
  const pending = deferred<Response>(); const calls: string[] = [];
  globalThis.fetch = ((url: RequestInfo | URL) => { calls.push(String(url)); return pending.promise; }) as unknown as typeof fetch;
  const qc = createQueryClient();
  render(<QueryClientProvider client={qc}><AuthGate><div>protected children</div></AuthGate></QueryClientProvider>);
  expect(screen.queryByText("protected children")).toBeNull();
  expect(calls).toEqual(["/api/v1/projects"]);
  await act(async () => { pending.resolve(response()); });
  await waitFor(() => expect(screen.getByText("protected children")).toBeTruthy());
  qc.setQueryData(["secret"], "private"); sessionStorage.setItem("hx-ws-sequence", "100");
  await act(async () => { auth.lock(auth.snapshot().generation); });
  expect(screen.queryByText("protected children")).toBeNull();
  expect(qc.getQueryData(["secret"])).toBeUndefined();
  expect(sessionStorage.getItem("hx-ws-sequence")).toBeNull();
});

test("wrong token stays gated, typed secret is cleared, valid unlock persists for reload", async () => {
  const { fireEvent } = await import("@testing-library/react");
  auth.select(null);
  globalThis.fetch = (async (_url: RequestInfo | URL, init?: RequestInit) => {
    return new Headers(init?.headers).get("Authorization") === "Bearer correct-synthetic" ? response() : response(401);
  }) as unknown as typeof fetch;
  const qc = createQueryClient();
  render(<QueryClientProvider client={qc}><AuthGate><div>private page</div></AuthGate></QueryClientProvider>);
  await waitFor(() => expect(auth.snapshot().status).toBe("locked"));
  fireEvent.change(screen.getByLabelText("Token"), { target: { value: "wrong-synthetic" } });
  fireEvent.click(screen.getByText("Unlock"));
  await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
  expect((screen.getByLabelText("Token") as HTMLInputElement).value).toBe("");
  expect(document.body.textContent).not.toContain("wrong-synthetic");
  fireEvent.change(screen.getByLabelText("Token"), { target: { value: "correct-synthetic" } });
  fireEvent.click(screen.getByText("Unlock"));
  await waitFor(() => expect(screen.getByText("private page")).toBeTruthy());
  const restored = new AuthStore(sessionStorage);
  expect(restored.capture().token).toBe("correct-synthetic");
  expect(restored.snapshot().status).toBe("validating");
});

test("locking cancels an in-flight query even when its fetch ignores AbortSignal", async () => {
  auth.select("old-synthetic");
  globalThis.fetch = (async () => response()) as unknown as typeof fetch;
  const qc = createQueryClient();
  render(<QueryClientProvider client={qc}><AuthGate><div>private query page</div></AuthGate></QueryClientProvider>);
  await waitFor(() => expect(screen.getByText("private query page")).toBeTruthy());
  const pending = deferred<Response>();
  globalThis.fetch = (() => pending.promise) as unknown as typeof fetch;
  const reading = qc.fetchQuery({ queryKey: ["projects"], queryFn: ({ signal }) => api.projects(signal) }).catch(() => null);
  await act(async () => { auth.lock(auth.snapshot().generation); });
  pending.resolve(new Response('[{"project":"old-private"}]'));
  await reading;
  expect(qc.getQueryCache().getAll()).toEqual([]);
  expect(screen.queryByText("private query page")).toBeNull();
});

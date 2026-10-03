import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";

import { RECENT_KEY, paletteShortcut, parseRecent, screenOf, updateRecent } from "../../src/shell/Header";
import { mockRoutes } from "../api/fetch-mock";
import { renderApp } from "../render-app";

const realFetch = globalThis.fetch;
beforeEach(() => {
  mockRoutes({});
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const tabs = () => within(screen.getByRole("navigation", { name: "Screens" })).getAllByRole("link");

describe("screenOf", () => {
  test("maps paths to screens", () => {
    expect(["/", "/t/toy/acc", "/t/toy/acc/edit/new", "/r/r1", "/x/r1/r2", "/nope"].map(screenOf)).toEqual([
      "overview",
      "task",
      "task",
      "run",
      "examples",
      null,
    ]);
  });
});

describe("updateRecent", () => {
  test("records the task, run and example pair, decoding segments", () => {
    let r = updateRecent({}, "/t/my%20proj/acc", {});
    r = updateRecent(r, "/r/r-9", {});
    r = updateRecent(r, "/x/r1/r2", { metric: "accuracy" });
    r = updateRecent(r, "/", {});
    expect(r).toEqual({
      task: { project: "my proj", task: "acc" },
      run: { runId: "r-9" },
      examples: { a: "r1", b: "r2", metric: "accuracy" },
    });
  });
});

test("parseRecent keeps only non-empty string fields", () => {
  expect(
    parseRecent({
      task: { project: "toy", task: "acc", extra: 1 },
      run: { runId: 7 },
      examples: { a: "r1", b: "r2", metric: 3 },
    }),
  ).toEqual({ task: { project: "toy", task: "acc" }, examples: { a: "r1", b: "r2" } });
  expect(parseRecent({ examples: { a: "r1", b: "r2", metric: "f1" } })).toEqual({
    examples: { a: "r1", b: "r2", metric: "f1" },
  });
  expect([parseRecent(null), parseRecent([]), parseRecent("x"), parseRecent({ task: { project: "" } })]).toEqual([
    {},
    {},
    {},
    {},
  ]);
});

test("paletteShortcut shows the platform's modifier", () => {
  expect([paletteShortcut("MacIntel"), paletteShortcut("Win32")]).toEqual(["⌘K", "Ctrl K"]);
});

describe("Header", () => {
  test("on first visit only Overview is a tab, and it is current", async () => {
    renderApp("/");
    await screen.findByRole("navigation", { name: "Screens" });
    await waitFor(() => expect(tabs().map((a) => a.getAttribute("aria-current"))).toEqual(["page"]));
    expect(tabs().map((a) => a.textContent)).toEqual(["Overview"]);
    expect(screen.getByRole("link", { name: "Hypothex, overview" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("button", { name: /Find a run, task or path/ })).toBeTruthy();
  });

  test("a corrupt stored value is ignored", async () => {
    localStorage.setItem(RECENT_KEY, "{not json");
    renderApp("/r/r-1");
    await screen.findByRole("navigation", { name: "Screens" });
    await waitFor(() => expect(tabs().map((a) => a.textContent)).toEqual(["Overview", "Run"]));
  });

  test("stored entries of the wrong shape are dropped, good ones kept", async () => {
    localStorage.setItem(
      RECENT_KEY,
      JSON.stringify({ task: { task: "x" }, run: { runId: "r-3" }, examples: { a: "r1", b: {} } }),
    );
    renderApp("/");
    await screen.findByRole("navigation", { name: "Screens" });
    await waitFor(() =>
      expect(tabs().map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
        ["Overview", "/"],
        ["Run", "/r/r-3"],
      ]),
    );
    for (const bad of ['{"task":"x"}', '{"task":{}}', '{"run":{"runId":""}}', "[1]", "null", "7"]) {
      cleanup();
      localStorage.setItem(RECENT_KEY, bad);
      renderApp("/");
      await screen.findByRole("navigation", { name: "Screens" });
      expect(tabs().map((a) => a.textContent)).toEqual(["Overview"]);
    }
  });

  test("remembers the last task and run as tabs", async () => {
    const { router } = renderApp("/t/toy/acc");
    await waitFor(() => expect(router.state.location.pathname).toBe("/t/toy/acc"));
    await act(() => router.navigate({ to: "/r/$runId", params: { runId: "r-7" } }));
    await waitFor(() =>
      expect(tabs().map((a) => [a.textContent, a.getAttribute("href"), a.getAttribute("aria-current")])).toEqual([
        ["Overview", "/", null],
        ["Task", "/t/toy/acc", null],
        ["Run", "/r/r-7", "page"],
      ]),
    );
    expect(JSON.parse(localStorage.getItem(RECENT_KEY) ?? "{}")).toEqual({
      task: { project: "toy", task: "acc" },
      run: { runId: "r-7" },
    });
  });

  test("shows nothing about live updates while the stream is ready", async () => {
    renderApp("/");
    await screen.findByRole("navigation", { name: "Screens" });
    expect(screen.queryByRole("status", { name: /Live updates/ })).toBeNull();
  });

  test("says when live updates are off or reconnecting", async () => {
    renderApp("/", { streamStatus: "offline" });
    const offline = await screen.findByRole("status", { name: "Live updates off" });
    expect(offline.textContent).toBe("● offline");
    expect(offline.getAttribute("title")).toMatch(/not live/);
    cleanup();
    renderApp("/", { streamStatus: "connected" });
    expect((await screen.findByRole("status", { name: "Live updates reconnecting" })).textContent).toBe(
      "● connecting",
    );
  });
});

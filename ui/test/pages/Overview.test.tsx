import { afterEach, expect, test } from "bun:test";
import { cleanup, screen, within } from "@testing-library/react";
import { OverviewPage } from "../../src/pages/Overview";
import { makeOverview } from "./fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

test("renders the headline, counts, and lettered panels", async () => {
  mockApi({ "GET /api/v1/overview": makeOverview() });
  renderWithClient(<OverviewPage />);
  const h1 = await screen.findByRole("heading", { level: 1 });
  expect(h1.textContent).toBe("Idle. SVM leads toy-test by 0.037, p = 0.15");
  for (const text of ["19 runs today", "3 failed", "1 task"]) expect(screen.getByText(text)).toBeTruthy();
  const names = screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
  expect(names).toEqual(["a Runs by launcher", "b Ideas", "c Running", "d Failures", "e Projects"]);
  expect(within(screen.getByRole("region", { name: "c Running" })).getByText("none")).toBeTruthy();
  const projects = screen.getByRole("region", { name: "e Projects" });
  expect(within(projects).getByText("0.9222")).toBeTruthy();
});

test("shows the server error", async () => {
  mockApi({ "GET /api/v1/overview": new HttpReply(500, { error: "index locked", type: "StoreError" }) });
  renderWithClient(<OverviewPage />);
  expect((await screen.findByRole("alert")).textContent).toBe("index locked");
});

import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { PropsSidebar } from "../../src/run/PropsSidebar";
import { costShown } from "../../src/pages/components/remote";
import { RUN_SVM, makeDetail } from "../pages/fixtures";
import { mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { MCCLEARY, NOW, lostRecord, remoteDetail } from "../pages/remoteFixtures";
import { makeCtx, propValue } from "./ctx";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const TAGS = `POST /api/v1/runs/${RUN_SVM}/tags`;

test("facts of a hub run, in order, with the task link", () => {
  mockApi({});
  renderWithClient(<PropsSidebar ctx={makeCtx({}, makeDetail({ params: { model: "svm", C: "1.0" } }))} />);
  const aside = screen.getByRole("complementary", { name: "Properties" });
  expect([...aside.querySelectorAll(".pgroup:first-child .prop .k")].map((k) => k.textContent)).toEqual([
    "Task", "Status", "Launcher", "Host", "Started", "Duration", "Commit",
  ]);
  expect(within(aside).getByRole("link", { name: "toy-classifier / toy-test" }).getAttribute("href")).toBe("/t/toy-classifier/toy-test");
  expect(propValue("Status")).toBe("Finished · exit 0");
  expect(propValue("Launcher")).toContain("acceptance");
  expect(within(aside).getByTitle("agent:acceptance")).toBeTruthy();
  expect(propValue("Host")).toBe("mbp.local");
  expect(propValue("Started")).toBe("2026-09-26 21:03");
  expect(propValue("Duration")).toBe("0.8 s");
  expect(propValue("Commit")).toBe("8f4cac4 · untracked");
  expect(aside.querySelector(".ids")?.textContent).toBe(`run ${RUN_SVM}`);
});

test("Config: values that vary in the task are tinted with the run's colour", () => {
  mockApi({});
  renderWithClient(<PropsSidebar ctx={makeCtx({}, makeDetail({ params: { model: "svm", C: "1.0" } }))} />);
  expect(propValue("model")).toBe("svm");
  expect(propValue("C")).toBe("1.0");
  expect([...document.querySelectorAll(".rside .chg")].map((c) => c.textContent)).toEqual(["svm", "3"]);
  expect(screen.getByText("tinted = varies in task")).toBeTruthy();
});

test("Tags: add with Enter, remove with ×; each posts a command", async () => {
  const calls = mockApi({ [TAGS]: makeDetail().record });
  renderWithClient(<PropsSidebar ctx={makeCtx()} />);
  fireEvent.click(screen.getByRole("button", { name: "Remove tag svm" }));
  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0]?.body).toMatchObject({ add: [], remove: ["svm"], created_by: "human" });
  fireEvent.click(screen.getByRole("button", { name: "+ Add" }));
  const input = screen.getByRole("textbox", { name: "New tag" });
  fireEvent.change(input, { target: { value: " final " } });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(calls).toHaveLength(2));
  expect(calls[1]?.body).toMatchObject({ add: ["final"], remove: [] });
});

test("an existing tag or an empty one posts nothing; Escape closes the input", async () => {
  const calls = mockApi({});
  renderWithClient(<PropsSidebar ctx={makeCtx()} />);
  const box = () => screen.queryByRole("textbox", { name: "New tag" });
  fireEvent.click(screen.getByRole("button", { name: "+ Add" }));
  fireEvent.change(screen.getByRole("textbox", { name: "New tag" }), { target: { value: "best" } });
  fireEvent.keyDown(screen.getByRole("textbox", { name: "New tag" }), { key: "Enter" });
  expect(box()).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "+ Add" }));
  fireEvent.keyDown(screen.getByRole("textbox", { name: "New tag" }), { key: "Enter" });
  expect(box()).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "+ Add" }));
  fireEvent.change(screen.getByRole("textbox", { name: "New tag" }), { target: { value: "draft" } });
  fireEvent.keyDown(screen.getByRole("textbox", { name: "New tag" }), { key: "Escape" });
  expect(box()).toBeNull();
  await new Promise((r) => setTimeout(r, 0));
  expect(calls).toHaveLength(0);
});

test("Notes keep the existing editor", () => {
  mockApi({});
  renderWithClient(<PropsSidebar ctx={makeCtx()} />);
  expect(screen.getByText("RBF SVM beats prior best (rf).")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add note" })).toBeTruthy();
});

test("a lost SLURM run: status, placement rows with copy, sweep link, cost", () => {
  mockApi({});
  const record = lostRecord({ tags: ["sweep:0a1b2c3d:s-7f3a"] });
  const ctx = makeCtx(
    { phase: "lost", host: MCCLEARY, hostsLoaded: true, remote: true, now: NOW, hubEnvId: "0a1b2c3d4e5f60718293a4b5c6d7e8f9", taskRuns: null },
    remoteDetail(record),
    null,
  );
  renderWithClient(<PropsSidebar ctx={ctx} />);
  expect(propValue("Project")).toBe("toy-classifier");
  expect(propValue("Status")).toBe("Lost · no exit code");
  expect(propValue("Host")).toBe("mccleary · slurm");
  expect(propValue("Job")).toBe("4471023");
  expect(screen.getByRole("button", { name: "Copy Job 4471023" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "s-7f3a" }).getAttribute("href")).toBe("/s/toy-classifier/s-7f3a");
  expect(propValue("Cost")).toBe(costShown(record.cost, MCCLEARY)?.value ?? "");
});

import { afterEach, expect, test } from "bun:test";
import { screen, within } from "@testing-library/react";
import { ExamplesTab } from "../../src/task/ExamplesTab";
import { parseSelection } from "../../src/task/useRunSelection";
import { mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { makeTaskRuns } from "./fixtures";

afterEach(restoreFetch);
const sel = parseSelection(new URLSearchParams(), { sortDir: "desc" });

test("compares the runner-up (A) with the best (B), latest finished run of each visible config", () => {
  mockApi({});
  renderWithClient(<ExamplesTab data={makeTaskRuns()} board={undefined} selection={sel} />);
  const a = screen.getByRole("combobox", { name: "Run A" }) as HTMLSelectElement;
  expect(a.value).toBe("run-b2");
  expect((screen.getByRole("combobox", { name: "Run B" }) as HTMLSelectElement).value).toBe("run-a2");
  expect(within(a).getAllByRole("option").map((o) => o.textContent)).toEqual(["lr 3e-4 · beam 10", "lr 1e-4 · beam 10"]);
});

test("needs two finished runs", () => {
  mockApi({});
  renderWithClient(<ExamplesTab data={makeTaskRuns()} board={undefined} selection={{ ...sel, hidden: ["g-b"] }} />);
  expect(screen.getByText("Needs two finished runs")).toBeTruthy();
});

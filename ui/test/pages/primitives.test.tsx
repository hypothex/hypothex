import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CopyButton } from "../../src/pages/components/CopyButton";
import { ErrorBox } from "../../src/pages/components/QueryState";
import { StatStrip } from "../../src/pages/components/StatStrip";
import { PAGES_CSS, PageStyles } from "../../src/pages/components/styles";
import { mockClipboard } from "./helpers";

afterEach(cleanup);

test("StatStrip shows value, unit, label, and tooltip", () => {
  render(<StatStrip items={[{ label: "wall", value: "68.4", unit: "s", tooltip: "wall-clock time" }]} />);
  const cell = screen.getByText("wall").parentElement as HTMLElement;
  expect(cell.getAttribute("title")).toBe("wall-clock time");
  expect(cell.querySelector("dd")?.textContent).toBe("68.4 s");
});

test("StatStrip renders nothing for no items", () => {
  const { container } = render(<StatStrip items={[]} />);
  expect(container.innerHTML).toBe("");
});

describe("CopyButton", () => {
  test("writes the text and marks itself copied", async () => {
    const written = mockClipboard();
    render(<CopyButton text="/runs/r1/logs/stderr.log" label="stderr path" />);
    const button = screen.getByRole("button", { name: "Copy stderr path" });
    fireEvent.click(button);
    await waitFor(() => expect(button.getAttribute("data-state")).toBe("copied"));
    expect(written).toEqual(["/runs/r1/logs/stderr.log"]);
  });

  test("shows a failure mark when the clipboard is blocked", async () => {
    mockClipboard(true);
    render(<CopyButton text="/x" />);
    const button = screen.getByRole("button", { name: "Copy /x" });
    fireEvent.click(button);
    await waitFor(() => expect(button.getAttribute("data-state")).toBe("failed"));
    expect(button.getAttribute("title")).toBe("Clipboard blocked");
  });
});

test("ErrorBox shows the message as an alert", () => {
  render(<ErrorBox error={new Error("no run abc")} />);
  expect(screen.getByRole("alert").textContent).toBe("no run abc");
});

test("PageStyles scopes every rule under .page", () => {
  const { container } = render(<PageStyles />);
  expect(container.querySelector("style[data-hx='pages']")?.textContent).toBe(PAGES_CSS);
  const selectors = PAGES_CSS.split("}")
    .map((block) => block.split("{").at(-2)?.trim() ?? "")
    .filter((sel) => sel && !sel.startsWith("/*"));
  for (const sel of selectors) {
    for (const part of sel.split(",")) expect(part.trim().startsWith(".page")).toBe(true);
  }
});

test("page spacing never shifts a full-screen panel off its fixed inset", () => {
  render(
    <div className="page">
      <PageStyles />
      <div className="side">
        <section className="panel">a</section>
        <section className="panel full" data-testid="full">b</section>
      </div>
      <section className="panel" data-testid="plain">c</section>
    </div>,
  );
  expect(getComputedStyle(screen.getByTestId("plain")).marginTop).toBe("24px");
  expect(["", "0px"]).toContain(getComputedStyle(screen.getByTestId("full")).marginTop);
});

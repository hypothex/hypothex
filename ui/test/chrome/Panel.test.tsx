import { describe, expect, mock, test } from "bun:test";
import { fireEvent, render, screen } from "@testing-library/react";
import { Panel } from "../../src/chrome/Panel";
import { PanelSection } from "../../src/chrome/PanelSection";

describe("Panel", () => {
  test("a region named by its title, with unit, aside and always-visible tools", () => {
    render(
      <Panel title="top1" unit="higher is better" aside="12 configs" tools={<button type="button">Bars</button>}>
        <p>body</p>
      </Panel>,
    );
    const region = screen.getByRole("region", { name: "top1" });
    expect(region.getAttribute("data-panel")).toBe("");
    expect(region.querySelector("h3.t")?.textContent).toBe("top1");
    expect(region.querySelector(".u")?.textContent).toBe("higher is better");
    expect(region.querySelector(".aside")?.textContent).toBe("12 configs");
    expect(screen.getByRole("button", { name: "Bars" })).not.toBeNull();
    expect(region.textContent).toContain("body");
  });

  test("no aside, no edit, no menu: only Full screen is offered", () => {
    render(<Panel title="val/loss">x</Panel>);
    const region = screen.getByRole("region", { name: "val/loss" });
    expect(region.querySelector(".aside")).toBeNull();
    expect([...region.querySelectorAll(".pacts button")].map((b) => b.getAttribute("aria-label"))).toEqual(["Full screen"]);
  });

  test("Full screen toggles, and Escape leaves it", () => {
    render(<Panel title="val/loss">x</Panel>);
    const region = screen.getByRole("region", { name: "val/loss" });
    const full = screen.getByRole("button", { name: "Full screen" });
    fireEvent.click(full);
    expect([region.className, full.getAttribute("aria-pressed")]).toEqual(["panel full", "true"]);
    fireEvent.keyDown(document, { key: "Escape" });
    expect([region.className, full.getAttribute("aria-pressed")]).toEqual(["panel", "false"]);
  });

  test("Edit calls back; More opens a menu that closes on pick, Escape and outside clicks", () => {
    const edit = mock(() => {});
    const dup = mock(() => {});
    render(
      <>
        <Panel title="lr" onEdit={edit} menu={[{ label: "Duplicate", onSelect: dup }, { label: "Remove", onSelect: () => {} }]}>
          x
        </Panel>
        <p data-testid="outside">elsewhere</p>
      </>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit panel" }));
    expect(edit).toHaveBeenCalledTimes(1);
    const more = screen.getByRole("button", { name: "More" });
    expect(more.getAttribute("aria-haspopup")).toBe("menu");
    fireEvent.click(more);
    expect(screen.getAllByRole("menuitem").map((m) => m.textContent)).toEqual(["Duplicate", "Remove"]);
    fireEvent.click(screen.getByRole("menuitem", { name: "Duplicate" }));
    expect(dup).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(more);
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(more);
    fireEvent.pointerDown(screen.getByTestId("outside"));
    expect(screen.queryByRole("menu")).toBeNull();
  });

  test("Escape on the More button closes the menu; in full screen it closes the menu first", () => {
    render(
      <Panel title="lr" menu={[{ label: "Remove", onSelect: () => {} }]}>
        x
      </Panel>,
    );
    const region = screen.getByRole("region", { name: "lr" });
    const more = screen.getByRole("button", { name: "More" });
    fireEvent.click(screen.getByRole("button", { name: "Full screen" }));
    fireEvent.click(more);
    fireEvent.keyDown(more, { key: "Escape" });
    expect([screen.queryByRole("menu") === null, region.className]).toEqual([true, "panel full"]);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(region.className).toBe("panel");
  });
});

describe("PanelSection", () => {
  test("open by default: the header button is expanded and the panels sit in a 330 px grid", () => {
    render(
      <PanelSection title="Scores" count="top1@v1 · test set">
        <div data-testid="p" />
      </PanelSection>,
    );
    const head = screen.getByRole("button", { name: /Scores/ });
    expect(head.getAttribute("aria-expanded")).toBe("true");
    expect(head.querySelector(".n")?.textContent).toBe("top1@v1 · test set");
    expect(screen.getByTestId("p").parentElement?.className).toBe("pgrid");
  });

  test("closed sections do not render their panels; toggling persists per task", () => {
    const { unmount } = render(
      <PanelSection title="top10" defaultOpen={false} storageKey="rxn/eval" grid="small">
        <div data-testid="p" />
      </PanelSection>,
    );
    expect(screen.queryByTestId("p")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /top10/ }));
    expect(screen.getByTestId("p").parentElement?.className).toBe("pgrid small");
    expect(localStorage.getItem("hx-section:rxn/eval:top10")).toBe("1");
    unmount();
    render(
      <PanelSection title="top10" defaultOpen={false} storageKey="rxn/eval">
        <div data-testid="p" />
      </PanelSection>,
    );
    expect(screen.getByTestId("p")).not.toBeNull();
    render(
      <PanelSection title="top10" defaultOpen={false} storageKey="rxn/other">
        <div data-testid="q" />
      </PanelSection>,
    );
    expect(screen.queryByTestId("q")).toBeNull();
  });

  test("+ Add panel only when the page offers it", () => {
    const add = mock(() => {});
    render(<PanelSection title="Eval">x</PanelSection>);
    expect(screen.queryByRole("button", { name: "+ Add panel" })).toBeNull();
    render(<PanelSection title="Training" onAddPanel={add}>x</PanelSection>);
    fireEvent.click(screen.getByRole("button", { name: "+ Add panel" }));
    expect(add).toHaveBeenCalledTimes(1);
  });
});

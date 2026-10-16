import { describe, expect, mock, test } from "bun:test";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { Button } from "../../src/chrome/Button";
import { Chip } from "../../src/chrome/Chip";
import { FilterField } from "../../src/chrome/FilterField";
import { Segmented } from "../../src/chrome/Segmented";

describe("Button", () => {
  test("is a plain button by default with the v5 classes", () => {
    const click = mock(() => {});
    render(
      <>
        <Button onClick={click}>Compare</Button>
        <Button variant="primary" size="sm" icon="plus">
          New run
        </Button>
        <Button variant="ghost" iconOnly icon="more" aria-label="More actions" />
      </>,
    );
    const compare = screen.getByRole("button", { name: "Compare" });
    expect([compare.getAttribute("type"), compare.className]).toEqual(["button", "btn"]);
    fireEvent.click(compare);
    expect(click).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "New run" }).className).toBe("btn primary sm");
    expect(screen.getByRole("button", { name: "New run" }).querySelector("svg")).not.toBeNull();
    expect(screen.getByRole("button", { name: "More actions" }).className).toBe("btn ghost icon");
  });

  test("a disabled button does not fire", () => {
    const click = mock(() => {});
    render(
      <Button disabled onClick={click}>
        Stop
      </Button>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(click).not.toHaveBeenCalled();
  });
});

describe("Chip", () => {
  test("a toggle chip reports aria-pressed; a menu chip shows a chevron and no aria-pressed", () => {
    render(
      <>
        <Chip on onClick={() => {}}>
          3 superseded hidden
        </Chip>
        <Chip on={false}>Superseded shown</Chip>
        <Chip chevron title="Sort by">
          Sort <b>top1 ↓</b>
        </Chip>
      </>,
    );
    expect(screen.getByRole("button", { name: "3 superseded hidden" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "3 superseded hidden" }).className).toBe("chip on");
    expect(screen.getByRole("button", { name: "Superseded shown" }).getAttribute("aria-pressed")).toBe("false");
    const sort = screen.getByRole("button", { name: /Sort/ });
    expect(sort.getAttribute("aria-pressed")).toBeNull();
    expect(sort.querySelector(".chev svg")).not.toBeNull();
  });
});

describe("Segmented", () => {
  test("a named group of pressed-state buttons; clicking picks the option", () => {
    function Harness() {
      const [v, setV] = useState<"config" | "run">("config");
      return (
        <Segmented
          label="Group"
          value={v}
          onChange={setV}
          options={[
            ["config", "By config"],
            ["run", "Each run"],
          ]}
        />
      );
    }
    render(<Harness />);
    const group = screen.getByRole("group", { name: "Group" });
    const pressed = () => [...group.querySelectorAll("button")].map((b) => b.getAttribute("aria-pressed"));
    expect(pressed()).toEqual(["true", "false"]);
    fireEvent.click(screen.getByRole("button", { name: "Each run" }));
    expect(pressed()).toEqual(["false", "true"]);
    expect(screen.getByRole("button", { name: "Each run" }).className).toBe("on");
  });
});

describe("FilterField", () => {
  test("a search box: typing reports the text, Escape clears it", () => {
    function Harness() {
      const [q, setQ] = useState("");
      return (
        <>
          <FilterField value={q} onChange={setQ} placeholder="Filter  lr=3e-4 · tag:final" label="Filter runs" />
          <output>{q}</output>
        </>
      );
    }
    render(<Harness />);
    expect(screen.getByRole("search")).not.toBeNull();
    const input = screen.getByRole("searchbox", { name: "Filter runs" });
    fireEvent.change(input, { target: { value: "tag:final" } });
    expect(screen.getByRole("status").textContent).toBe("tag:final");
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.getByRole("status").textContent).toBe("");
  });
});

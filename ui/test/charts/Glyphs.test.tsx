import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import {
  BestBand,
  CheckpointMark,
  IdenticalSeeds,
  Key,
  KillMark,
  MeanMark,
  SeedDots,
  SpikeMark,
  Whisker,
  diamondPath,
  stackSeeds,
} from "../../src/charts/Glyphs";

afterEach(cleanup);

describe("stackSeeds", () => {
  test("close dots stack, far dots reset to level 0", () => {
    expect(stackSeeds([50, 10, 13, 16, 30])).toEqual([
      { x: 10, level: 0 },
      { x: 13, level: 1 },
      { x: 16, level: 2 },
      { x: 30, level: 0 },
      { x: 50, level: 0 },
    ]);
  });
  test("identical positions stack upward", () => {
    expect(stackSeeds([5, 5]).map((d) => d.level)).toEqual([0, 1]);
    expect(stackSeeds([])).toEqual([]);
  });
});

test("SeedDots draws one dot per finite seed, 8 px per stack level", () => {
  const { container } = render(
    <svg>
      <SeedDots x={(v) => v * 100} values={[0.1, 0.12, 0.5, Number.NaN]} y={30} />
    </svg>,
  );
  const dots = [...container.querySelectorAll("circle.seed")];
  expect(dots.length).toBe(3);
  expect(dots.map((d) => d.getAttribute("cy"))).toEqual(["30", "22", "30"]);
});

test("diamondPath is a closed rhombus", () => {
  expect(diamondPath(10, 20, 5)).toBe("M10 15L15 20L10 25L5 20Z");
});

test("IdenticalSeeds shows ×n right of the diamond, left for the best row", () => {
  const { container, rerender } = render(
    <svg>
      <IdenticalSeeds cx={100} cy={30} n={3} />
    </svg>,
  );
  let label = container.querySelector("text");
  expect(label?.textContent).toBe("×3");
  expect(label?.getAttribute("x")).toBe("111");
  expect(container.querySelector("path.dia")?.getAttribute("class")).toBe("dia");
  rerender(
    <svg>
      <IdenticalSeeds cx={100} cy={30} n={3} best />
    </svg>,
  );
  label = container.querySelector("text");
  expect(label?.getAttribute("x")).toBe("89");
  expect(label?.getAttribute("text-anchor")).toBe("end");
  expect(container.querySelector("path.dia")?.getAttribute("class")).toBe("dia best");
});

test("MeanMark, Whisker and BestBand geometry", () => {
  const { container } = render(
    <svg>
      <MeanMark cx={50} cy={58} best />
      <Whisker x1={20} x2={80} y={58} />
      <BestBand x1={90} x2={60} y0={0} y1={104} />
    </svg>,
  );
  const sq = container.querySelector("rect.mean");
  expect(sq?.getAttribute("x")).toBe("45.5");
  expect(sq?.getAttribute("width")).toBe("9");
  expect(sq?.getAttribute("class")).toBe("mean best");
  expect(container.querySelector("path.whisk")?.getAttribute("d")).toBe("M20 58H80M20 54V62M80 54V62");
  const band = container.querySelector("rect.band");
  expect(band?.getAttribute("x")).toBe("60");
  expect(band?.getAttribute("width")).toBe("30");
  expect(container.querySelectorAll("line.band-edge").length).toBe(2);
});

test("event and checkpoint marks use their classes", () => {
  const { container } = render(
    <svg>
      <SpikeMark x={10} y={10} />
      <KillMark x={20} y={20} r={4} />
      <CheckpointMark cx={30} cy={30} />
      <CheckpointMark cx={40} cy={40} best />
    </svg>,
  );
  expect(container.querySelector("path.evg")?.getAttribute("d")).toBe("M4 14H7.5L10 5L12.5 14H16");
  expect(container.querySelector("path.m-fail")?.getAttribute("d")).toBe("M16 16L24 24M24 16L16 24");
  expect(container.querySelector("circle.ck")?.getAttribute("r")).toBe("3.2");
  expect(container.querySelector("circle.m-best")?.getAttribute("r")).toBe("4.5");
});

test("Key renders one labelled glyph per item with its tooltip", () => {
  render(
    <Key
      items={[
        { glyph: "seed", label: "seed" },
        { glyph: "identical", label: "×3 identical seeds", title: "All seeds gave one score" },
      ]}
    />,
  );
  const key = screen.getByLabelText("Key");
  expect(key.querySelectorAll("svg").length).toBe(2);
  expect(key.querySelector("[data-glyph=identical]")).not.toBeNull();
  expect(screen.getByTitle("All seeds gave one score").textContent).toBe("×3 identical seeds");
});

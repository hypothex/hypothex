import { expect, test } from "bun:test";
import { IDENTITY_SLOTS, NEUTRAL, colorFor } from "../../src/lib/color";
import { cx } from "../../src/lib/cx";

test("visible identities take c1..c8 in list order", () => {
  const order = ["a", "b", "c"];
  expect(order.map((id) => colorFor(id, order))).toEqual(["var(--c1)", "var(--c2)", "var(--c3)"]);
  expect(IDENTITY_SLOTS).toBe(8);
});

test("the 9th visible identity and anything not visible are neutral", () => {
  const order = Array.from({ length: 10 }, (_, i) => `g${i}`);
  expect(order.map((id) => colorFor(id, order))).toEqual([
    "var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)", "var(--c7)", "var(--c8)",
    NEUTRAL, NEUTRAL,
  ]);
  expect(colorFor("hidden", order)).toBe("var(--c0)");
});

test("a colour follows its identity's place, so hiding one shifts the rest", () => {
  expect(colorFor("c", ["a", "b", "c"])).toBe("var(--c3)");
  expect(colorFor("c", ["a", "c"])).toBe("var(--c2)");
});

test("cx joins truthy class names", () => {
  expect(cx("chip", false, null, undefined, "on", "")).toBe("chip on");
});

import { expect, test } from "bun:test";
import { freePort } from "../../e2e/paths";

/** Playwright workers use Node even when Bun launches the runner. */
test("free-port helper returns a number under the colored Playwright Node environment", () => {
  const oldForce = process.env.FORCE_COLOR;
  const oldNoColor = process.env.NO_COLOR;
  process.env.FORCE_COLOR = "1";
  process.env.NO_COLOR = "1";
  try {
    const port = freePort("node");
    expect(Number.isInteger(port)).toBe(true);
    expect(port).toBeGreaterThan(0);
    expect(port).toBeLessThan(65536);
  } finally {
    if (oldForce === undefined) delete process.env.FORCE_COLOR;
    else process.env.FORCE_COLOR = oldForce;
    if (oldNoColor === undefined) delete process.env.NO_COLOR;
    else process.env.NO_COLOR = oldNoColor;
  }
});

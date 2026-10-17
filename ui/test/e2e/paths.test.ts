import { expect, test } from "bun:test";
import { freePort, TEAM_PORT, TEAM_DARK_PORT, PORT, HOSTS_PORT, VITE_PORT, TEAM_HOME_DIR, TEAM_DARK_HOME_DIR, RUN_DIR, localToken } from "../../e2e/paths";

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

test("team homes and ports are isolated and token helper rejects arbitrary homes", () => {
  expect(new Set([TEAM_PORT,TEAM_DARK_PORT,PORT,HOSTS_PORT,VITE_PORT]).size).toBe(5);
  expect(TEAM_HOME_DIR.startsWith(`${RUN_DIR}/`)).toBe(true);
  expect(TEAM_DARK_HOME_DIR.startsWith(`${RUN_DIR}/`)).toBe(true);
  expect(TEAM_HOME_DIR).not.toBe(TEAM_DARK_HOME_DIR);
  expect(()=>localToken('/tmp/not-owned-hypothex')).toThrow('Not an isolated test home');
});

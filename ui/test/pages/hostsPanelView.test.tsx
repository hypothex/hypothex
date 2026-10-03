import { expect, test } from "bun:test";
import { render, screen, within } from "@testing-library/react";
import { HOSTS_CSS, HostsPanel, StateGlyph } from "../../src/pages/components/HostsPanel";
import type { ConnState } from "../../src/pages/components/types";
import { NOW, RUN_AGENT, gpu, makeHostRuns, makeHosts } from "./hostFixtures";

function renderPanel(hosts = makeHosts(), hubVersion: string | null = "0.5.0") {
  return render(<HostsPanel hosts={hosts} runs={makeHostRuns()} hubVersion={hubVersion} now={NOW} />);
}

test("one row per host, in API order, under a header with GPU indices 0-7", () => {
  const { container } = renderPanel();
  expect(screen.getAllByRole("group").map((g) => g.getAttribute("aria-label"))).toEqual([
    "gpu1",
    "dgx",
    "mccleary",
    "gpu2",
  ]);
  const idx = [...container.querySelectorAll(".hrow.head .gidx span")].map((s) => s.textContent);
  expect(idx).toEqual(["0", "1", "2", "3", "4", "5", "6", "7"]);
  expect(container.querySelector("style[data-hx='hosts']")?.textContent).toBe(HOSTS_CSS);
});

test("gpu1: agent, not-hx, human and free cells; version mismatch; queue, rate, cost", () => {
  const { container } = renderPanel();
  const row = within(screen.getByRole("group", { name: "gpu1" }));
  expect(row.getByText("ssh")).toBeTruthy();
  expect(row.getByText("5×A100 80GB")).toBeTruthy();
  expect(row.getByText("connected")).toBeTruthy();

  const [agent, human] = row.getAllByRole("link") as [HTMLElement, HTMLElement];
  expect(agent.getAttribute("href")).toBe(`/r/${RUN_AGENT}`);
  expect(agent.className).toBe("gc busy agent");
  expect(agent.style.gridColumn).toBe("1 / span 2");
  expect(agent.textContent).toBe("6b0e92% ×2");
  expect(agent.getAttribute("title")).toBe("gpu1 GPU 0–1: 6b0e\nlr 3e-4\nagent:tuner\nGPU 0 92%, GPU 1 91%, 60.0 GB");
  expect(human.className).toBe("gc busy human");
  expect(human.getAttribute("title")).toBe("gpu1 GPU 3: 52c9\n+aug long\nhuman:shreyas\nGPU 3 77%, 20.0 GB");

  const cells = [...container.querySelectorAll("[aria-label='gpu1'] .cells > *")];
  expect(cells.map((c) => c.className)).toEqual(["gc busy agent", "gc other", "gc busy human", "gc free"]);
  expect(cells[1]?.textContent).toBe("not hx63%");
  expect(cells[3]?.getAttribute("title")).toBe("gpu1 GPU 4: free");

  const ver = row.getByTitle("hub runs hx 0.5.0. Update: hx hosts upgrade gpu1");
  expect(ver.textContent).toBe("hx 0.4.1≠");
  const [queue, rate, today] = [...container.querySelectorAll("[aria-label='gpu1'] > .r")];
  expect([queue?.textContent, rate?.textContent, today?.textContent]).toEqual(["3", "$1.10", "$106"]);
});

test("dgx: stale for 4m, greyed last-known cells with 'as of' in tooltips", () => {
  renderPanel();
  const group = screen.getByRole("group", { name: "dgx" });
  expect(group.className).toBe("hrow stale");
  const row = within(group);
  expect(row.getByText("stale 4m").tagName).toBe("B");
  expect(row.getByText("hx 0.5.0").getAttribute("title")).toBe("hx 0.5.0");
  expect(group.querySelector(".hs .meta")?.textContent).toBe("hx 0.5.0  as of 14:27");
  const cell = row.getByRole("link");
  expect(cell.className).toBe("gc busy run");
  expect(cell.getAttribute("title")).toBe("dgx GPU 0: 8e41\nGPU 0 95%, 0.0 GB\nas of 14:27");
});

test("mccleary: SLURM running and pending counts instead of GPU cells", () => {
  renderPanel();
  const group = screen.getByRole("group", { name: "mccleary" });
  expect(group.querySelector(".cells")).toBeNull();
  expect(group.querySelector(".slurm")?.textContent).toBe("4running6pending");
  const [queue, rate, today] = [...group.querySelectorAll(":scope > .r")];
  expect([queue?.textContent, queue?.className, rate?.textContent, today?.textContent]).toEqual([
    "0",
    "r q z",
    "$0.50",
    "$19",
  ]);
});

test("gpu2: bootstrapping shows the step message, unknown version and no rate", () => {
  renderPanel();
  const group = screen.getByRole("group", { name: "gpu2" });
  const row = within(group);
  expect(row.getByText("bootstrapping")).toBeTruthy();
  expect(group.querySelector(".msg")?.textContent).toBe("3/5 uv, hx 0.5.0");
  expect(row.getByText("hx ·")).toBeTruthy();
  const [, rate, today] = [...group.querySelectorAll(":scope > .r")];
  expect([rate?.textContent, today?.textContent]).toEqual(["·", "·"]);
});

test("no hub version: no mismatch mark", () => {
  renderPanel(makeHosts(), null);
  const row = screen.getByRole("group", { name: "gpu1" });
  expect(row.querySelector(".ne")).toBeNull();
  expect(row.querySelector(".ver")?.textContent).toBe("hx 0.4.1");
});

test("a 12-GPU host widens every row to 12 columns", () => {
  const hosts = makeHosts();
  hosts[0] = { ...hosts[0]!, gpus: [gpu(0), gpu(11, { run_id: RUN_AGENT, util: 50 })] };
  const { container } = renderPanel(hosts);
  expect(container.querySelectorAll(".hrow.head .gidx span")).toHaveLength(12);
  const cells = container.querySelector("[aria-label='gpu1'] .cells") as HTMLElement;
  expect(cells.style.gridTemplateColumns).toBe("repeat(12, minmax(0, 1fr))");
  expect((cells.lastElementChild as HTMLElement).style.gridColumn).toBe("12 / span 1");
});

test("a connected host with no GPUs says so; an empty list says none", () => {
  const hosts = makeHosts();
  hosts[0] = { ...hosts[0]!, gpus: [] };
  renderPanel(hosts);
  expect(screen.getByRole("group", { name: "gpu1" }).querySelector(".msg")?.textContent).toBe("no GPUs");
  const { container } = render(<HostsPanel hosts={[]} runs={[]} hubVersion="0.5.0" now={NOW} />);
  expect(container.textContent).toBe("none");
});

test("the key names every cell kind and mark", () => {
  renderPanel();
  const key = screen.getByLabelText("Key");
  expect(key.textContent).toBe("agent runhuman runfreenot hxstalehx≠version mismatch");
});

test("StateGlyph: every ConnState has its own SVG shape", () => {
  const states: ConnState[] = ["connecting", "bootstrapping", "connected", "stale", "upgrade", "error", "disabled"];
  const shapes = states.map((state) => {
    const { container, unmount } = render(<StateGlyph state={state} />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("data-state")).toBe(state);
    // Children only, so the data-state attribute cannot make two glyphs differ.
    const shape = svg?.innerHTML ?? "";
    unmount();
    return shape;
  });
  expect(shapes.every((s) => s.length > 0)).toBe(true);
  expect(new Set(shapes).size).toBe(states.length);
});

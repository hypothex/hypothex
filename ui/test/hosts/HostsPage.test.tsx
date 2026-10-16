import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ConnState } from "../../src/api/models";
import { HostsPage } from "../../src/hosts/HostsPage";
import { StateGlyph } from "../../src/pages/components/HostsPanel";
import { mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { localRow, makeHosts } from "../pages/hostFixtures";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const ENV = { "GET /.well-known/hypothex/environment": { environment_id: "env-hub", hx_version: "0.5.0" } };

test("one row per host with one cell per GPU, state, version mismatch, queue, rate, cost", async () => {
  mockApi({ "GET /api/v1/hosts": [localRow(), ...makeHosts()], ...ENV });
  renderWithClient(<HostsPage />);
  const gpu1 = await screen.findByRole("row", { name: "gpu1" });
  expect(gpu1.querySelectorAll("[data-gpu]")).toHaveLength(5);
  await waitFor(() => expect(within(gpu1).getByText("≠")).toBeTruthy());
  expect(within(gpu1).getByRole("link", { name: "3" }).getAttribute("href")).toBe("/queue");
  expect(within(gpu1).getByText("$1.10")).toBeTruthy();
  expect(screen.getByRole("row", { name: "dgx" }).className).toBe("stale");
  expect(within(screen.getByRole("row", { name: "mccleary" })).getByText("4 running · 6 pending")).toBeTruthy();
  expect(screen.getByRole("row", { name: "local" }).querySelectorAll("button")).toHaveLength(0);
  expect(screen.getByText("5 hosts")).toBeTruthy();
});

test("Disconnect, Reconnect and Reload post to the hub", async () => {
  const calls = mockApi({
    "GET /api/v1/hosts": makeHosts(),
    ...ENV,
    "POST /api/v1/hosts/gpu1/disconnect": { ...makeHosts()[0]!.state, state: "disabled" },
    "POST /api/v1/hosts/dgx/connect": { ...makeHosts()[1]!.state, state: "connecting" },
    "POST /api/v1/hosts/reload": makeHosts(),
  });
  renderWithClient(<HostsPage />);
  fireEvent.click(within(await screen.findByRole("row", { name: "gpu1" })).getByRole("button", { name: "Disconnect" }));
  fireEvent.click(within(screen.getByRole("row", { name: "dgx" })).getByRole("button", { name: "Reconnect" }));
  fireEvent.click(screen.getByRole("button", { name: "Reload" }));
  await waitFor(() =>
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url).sort()).toEqual([
      "/api/v1/hosts/dgx/connect",
      "/api/v1/hosts/gpu1/disconnect",
      "/api/v1/hosts/reload",
    ]),
  );
  expect(within(screen.getByRole("row", { name: "gpu2" })).getByRole("button", { name: "Connecting" }).hasAttribute("disabled")).toBe(true);
});

test("a host stale for more than a day gets a banner", async () => {
  const hosts = makeHosts().map((h) => (h.name === "dgx" ? { ...h, state: { ...h.state, since: "2026-09-20T00:00:00Z" } } : h));
  mockApi({ "GET /api/v1/hosts": hosts, ...ENV });
  renderWithClient(<HostsPage />);
  await waitFor(() => expect(screen.getByRole("status").textContent).toMatch(/^dgx unreachable \d+d$/));
});

test("StateGlyph: every ConnState has its own SVG shape", () => {
  const states: ConnState[] = ["connecting", "bootstrapping", "connected", "stale", "upgrade", "error", "disabled"];
  const shapes = states.map((state) => {
    const { container, unmount } = render(<StateGlyph state={state} />);
    const svg = container.querySelector("svg");
    const html = svg?.innerHTML ?? "";
    unmount();
    return html;
  });
  expect(new Set(shapes).size).toBe(states.length);
});

test("launch-only readers cannot administer hosts and auth failures require explicit repair", async () => {
  const hosts=makeHosts();hosts[0]={...hosts[0]!,state:{...hosts[0]!.state,state:'error',message:'auth failed: hx hosts pair gpu1 <pairing-url>'}};
  const calls=mockApi({...ENV,'GET /api/v1/hosts':hosts,'GET /api/v1/auth/me':{auth:'on',user:'alice',scope:'launch',scopes:['read','launch'],session_id:'s_1',client:'browser',public_url:null}});
  renderWithClient(<HostsPage/>);const gpu=await screen.findByRole('row',{name:'gpu1'});expect(within(gpu).getByRole('status').textContent).toContain('hx hosts pair');
  for(const button of screen.getAllByRole('button')) expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(within(gpu).getByRole('button',{name:'Reconnect'}));fireEvent.click(screen.getByRole('button',{name:'Reload'}));expect(calls.some(call=>call.method==='POST')).toBe(false);
});
test("admin sees auth repair instructions instead of replaying a failed credential", async () => {
 const hosts=makeHosts();hosts[0]={...hosts[0]!,state:{...hosts[0]!.state,state:'error',message:'auth failed: hx hosts pair gpu1 <pairing-url>'}};mockApi({...ENV,'GET /api/v1/hosts':hosts});renderWithClient(<HostsPage/>);const row=await screen.findByRole('row',{name:'gpu1'});expect((within(row).getByRole('button',{name:'Reconnect'}) as HTMLButtonElement).disabled).toBe(true);
});

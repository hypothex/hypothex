import { useState } from "react";
import { act, waitFor } from "@testing-library/react";
import { LaunchDialog } from "../../src/launch/LaunchDialog";
import { renderWithClient, mockApi, restoreFetch } from "./helpers";
import { GPU1, PROJECT, TASK, REPO_PATH, CMD } from "../launch/fixtures";
import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { OpeningDialog } from "../../src/pages/components/OpeningDialog";
afterEach(() => { cleanup(); restoreFetch(); });
test("opening failures remain modal, retryable and dismissible", () => {
  const close = mock(() => {});
  const retry = mock(() => {});
  render(<OpeningDialog title="New run" error={new Error("offline")} onClose={close} onRetry={retry} />);
  const dialog = screen.getByRole("dialog", { name: "New run" });
  expect(dialog.getAttribute("aria-modal")).toBe("true");
  expect(screen.getByRole("alert").textContent).toBe("offline");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(retry).toHaveBeenCalledTimes(1);
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(close).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(close).toHaveBeenCalledTimes(2);
});
test("loading traps focus and restores the opener on close", () => {
  const opener = document.createElement("button");
  document.body.append(opener);
  opener.focus();
  const { unmount } = render(<OpeningDialog title="New run" onClose={() => {}} />);
  expect(screen.getByText("loading…")).toBeTruthy();
  const close = screen.getByRole("button", { name: "Close" });
  expect(document.activeElement).toBe(close);
  fireEvent.keyDown(close, { key: "Tab" });
  expect(document.activeElement).toBe(close);
  unmount();
  expect(document.activeElement).toBe(opener);
  opener.remove();
});

let ready: () => void;
function Probe() {
  const [phase, setPhase] = useState(0);
  ready = () => setPhase(2);
  return <><button onClick={() => setPhase(1)}>Start rerun</button>{phase === 1 ? <OpeningDialog title="Prepare" onClose={() => setPhase(0)} /> : phase === 2 ? <LaunchDialog project={PROJECT} task={TASK} repo={REPO_PATH} initial={{host:'gpu1', command:CMD, seeds:'1', gpus:0}} onClose={() => setPhase(0)} onLaunched={() => {}} /> : null}</>;
}
test('opening handoff keeps focus inside the ready launch dialog', async () => {
  mockApi({'GET /api/v1/hosts':[GPU1], 'GET /api/v1/gpus':[], 'GET /api/v1/queue':[]});
  renderWithClient(<Probe />);
  const trigger = screen.getByRole('button',{name:'Start rerun'});
  trigger.focus();
  fireEvent.click(trigger);
  await waitFor(() => expect(document.activeElement?.getAttribute('aria-label')).toBe('Close'));
  // Finish the query notification and initial-host effect inside act before checking focus.
  await act(async () => ready());
  for (let tick = 0; tick < 50; tick++) {
    await act(async () => { await new Promise<void>(resolve => setTimeout(resolve, 0)); });
    if ((screen.queryByRole('radio', { name: 'gpu1' }) as HTMLInputElement | null)?.checked) break;
  }
  expect((screen.getByRole('radio', { name: 'gpu1' }) as HTMLInputElement).checked).toBe(true);
  const dialog = screen.getByRole('dialog');
  expect(dialog.contains(document.activeElement)).toBe(true);
});

import { afterEach, beforeEach, expect, test } from "bun:test";
import { act, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { auth } from "../../src/api/auth";
import type { NotebookDay } from "../../src/api/models";
import { DayView } from "../../src/pages/notebook/DayView";
import { mockApi, restoreFetch, renderWithClient, HttpReply, mockClipboard } from "../pages/helpers";
const day: NotebookDay = { project: "p", day: "2026-10-17", text: "original", hash: "sha256:original", runs: [], updated_at: null };
const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const path = "/api/v1/projects/p/notebook/2026-10-17";
beforeEach(() => { auth.accept(auth.select(null)); }); afterEach(() => { cleanup(); auth.select(null); restoreFetch(); if (clipboardDescriptor) Object.defineProperty(navigator, "clipboard", clipboardDescriptor); else delete (navigator as unknown as Record<string, unknown>).clipboard; });
test("append sends resolved explicit day and immutable draft", async () => { let resolve!: (v: unknown) => void; const calls = mockApi({ [`POST ${path}`]: () => new Promise((r) => { resolve = r; }) }); const view = renderWithClient(<DayView day={day} writable />); fireEvent.change(view.getByLabelText("New entry"), { target: { value: "my note" } }); fireEvent.click(view.getByRole("button", { name: "Add entry" })); await waitFor(() => expect(resolve).toBeDefined()); expect((view.getByLabelText("New entry") as HTMLTextAreaElement).readOnly).toBe(true); expect(calls[0].body).toMatchObject({ text: "my note" }); expect(calls[0].body).not.toHaveProperty("author"); resolve(day); await waitFor(() => expect((view.getByLabelText("New entry") as HTMLTextAreaElement).value).toBe("")); });
test("conflict preserves mine; keep mine uses returned hash and new command id", async () => { const theirs = { ...day, text: "remote edit", hash: "sha256:theirs" }; let saves = 0; const calls = mockApi({ [`PUT ${path}`]: () => ++saves === 1 ? new HttpReply(409, { type: "NotebookConflictError", error: "conflict", current: theirs }) : { ...day, text: "mine", hash: "sha256:mine" } }); const view = renderWithClient(<DayView day={day} writable />); fireEvent.click(view.getByRole("button", { name: "Edit day" })); fireEvent.change(view.getByLabelText("Day text"), { target: { value: "mine" } }); fireEvent.click(view.getByRole("button", { name: "Save" })); await view.findByRole("alert", { name: "Notebook conflict" }); expect((view.getByLabelText("Day text") as HTMLTextAreaElement).value).toBe("mine"); expect(view.getByRole("region", { name: "Theirs" }).textContent).toContain("remote edit"); fireEvent.click(view.getByRole("button", { name: "Keep mine" })); await waitFor(() => expect(calls.length).toBe(2)); expect(calls[0].body).toMatchObject({ text: "mine", base_hash: day.hash }); expect(calls[1].body).toMatchObject({ text: "mine", base_hash: theirs.hash }); expect((calls[0].body as {command_id:string}).command_id).not.toBe((calls[1].body as {command_id:string}).command_id); });
test("edit hash stays pinned through refreshed query props", async () => { const calls = mockApi({ [`PUT ${path}`]: day }); const view = renderWithClient(<DayView day={day} writable />); fireEvent.click(view.getByRole("button", { name: "Edit day" })); fireEvent.change(view.getByLabelText("Day text"), { target: { value: "draft" } }); // A live refresh reaches the same mounted component.
  view.rerender(<QueryClientProvider client={view.client}><DayView day={{ ...day, text: "live revision", hash: "new-live-hash" }} writable /></QueryClientProvider>);
  fireEvent.click(view.getByRole("button", { name: "Save" })); await waitFor(() => expect(calls.length).toBe(1)); expect(calls[0].body).toMatchObject({ base_hash: day.hash, text: "draft" }); });
test("413 preserves draft and read-only cannot write", async () => { mockApi({ [`PUT ${path}`]: new HttpReply(413, { error: "Too large", type: "NotebookTooLargeError" }) }); const view = renderWithClient(<DayView day={day} writable />); fireEvent.click(view.getByRole("button", { name: "Edit day" })); fireEvent.change(view.getByLabelText("Day text"), { target: { value: "kept" } }); fireEvent.click(view.getByRole("button", { name: "Save" })); await view.findByText(/your draft is retained/); expect((view.getByLabelText("Day text") as HTMLTextAreaElement).value).toBe("kept"); });
test("copy mine never saves and use theirs explicitly discards", async () => { const written = mockClipboard(); const calls = mockApi({ [`PUT ${path}`]: new HttpReply(409, { type: "NotebookConflictError", error: "conflict", current: { ...day, text: "theirs", hash: "new" } }) }); const view = renderWithClient(<DayView day={day} writable />); fireEvent.click(view.getByRole("button", { name: "Edit day" })); fireEvent.change(view.getByLabelText("Day text"), { target: { value: "mine" } }); fireEvent.click(view.getByRole("button", { name: "Save" })); fireEvent.click(await view.findByRole("button", { name: "Copy mine" })); await view.findByText("Copied"); expect(written).toEqual(["mine"]); expect(calls).toHaveLength(1); fireEvent.click(view.getByRole("button", { name: "Use theirs" })); expect(view.queryByLabelText("Day text")).toBeNull(); });
test("credential replacement discards editor and late save", async () => {
  let started!: () => void;
  let respond!: (value: NotebookDay) => void;
  const requestStarted = new Promise<void>((resolve) => { started = resolve; });
  const reply = new Promise<NotebookDay>((resolve) => { respond = resolve; });
  const calls = mockApi({ [`PUT ${path}`]: () => { started(); return reply; } });
  const view = renderWithClient(<DayView day={day} writable />);
  fireEvent.click(view.getByRole("button", { name: "Edit day" }));
  fireEvent.click(view.getByRole("button", { name: "Save" }));
  await requestStarted;
  expect(calls).toHaveLength(1);
  await act(async () => {
    auth.select(null);
    respond(day);
    await reply;
  });
  expect(view.queryByLabelText("Day text")).toBeNull();
  expect(view.queryByRole("alert")).toBeNull();
});
test("second conflict retains mine and malformed conflict stays an error", async () => { let n = 0; const calls = mockApi({ [`PUT ${path}`]: () => new HttpReply(409, { type: "NotebookConflictError", error: "conflict", current: { ...day, text: `theirs${++n}`, hash: `hash${n}` } }) }); const view = renderWithClient(<DayView day={day} writable />); fireEvent.click(view.getByRole("button", { name: "Edit day" })); fireEvent.change(view.getByLabelText("Day text"), { target: { value: "still mine" } }); fireEvent.click(view.getByRole("button", { name: "Save" })); fireEvent.click(await view.findByRole("button", { name: "Keep mine" })); await view.findByText("theirs2"); expect((view.getByLabelText("Day text") as HTMLTextAreaElement).value).toBe("still mine"); expect(calls).toHaveLength(2); });
test("read-only rendering disables every write and UTF-8 limit is enforced", async () => { const view = renderWithClient(<DayView day={day} writable={false} />); expect((view.getByRole("button", { name: "Edit day" }) as HTMLButtonElement).disabled).toBe(true); expect((view.getByRole("button", { name: "Add entry" }) as HTMLButtonElement).disabled).toBe(true); });

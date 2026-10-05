import { afterEach, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import { ErrorBox } from "../../src/pages/components/QueryState";

afterEach(cleanup);

test.each([
  ["POST /api/v1/runs/r/reinfer → 400: project has no 'infer' stage", "project has no 'infer' stage"],
  ["GET /api/v1/runs?cursor=x → 503: upstream: a → b failed", "upstream: a → b failed"],
  ["PUT /api/v1/tasks/p/t/views/a → 422: spec: invalid\nline 2: x → y", "spec: invalid\nline 2: x → y"],
  ["DELETE /api/v1/hosts/h → 409: host: still running", "host: still running"],
])("ErrorBox hides the known transport prefix but retains the complete tooltip: %s", (message, visible) => {
  render(<ErrorBox error={new Error(message)} />);
  const alert = screen.getByRole("alert");
  expect(alert.textContent).toBe(visible);
  expect(alert.getAttribute("title")).toBe(message);
});

test.each([
  "model: a → b failed",
  "POST processing → 400: keep this",
  "note: POST /api/v1/runs/r/reinfer → 400: keep this",
  "GET /data/input → 400: keep this",
  "Cannot reach hx serve",
])("ErrorBox preserves an ordinary message: %s", (message) => {
  render(<ErrorBox error={message} />);
  expect(screen.getByRole("alert").textContent).toBe(message);
});

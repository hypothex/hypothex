import { expect, test } from "bun:test";
import { fireEvent, render } from "@testing-library/react";
import { OpeningDialog } from "../../src/pages/components/OpeningDialog";
import { CleanupDialog } from "../../src/pages/storage/CleanupDialog";

test("export dialog has an explicit name independent of generated heading IDs", () => {
  const view = render(<OpeningDialog title="Export" onClose={() => {}}><p>Preview</p></OpeningDialog>);
  const dialog = view.getByRole("dialog", { name: "Export" });
  expect(dialog.getAttribute("aria-label")).toBe("Export");
  expect(dialog.hasAttribute("aria-labelledby")).toBe(false);
  expect(view.getByRole("heading", { name: "Export" }).textContent).toBe("Export");
});

test("cleanup keeps its explicit name while deletion prevents dismissal", () => {
  let dismissed = false;
  const view = render(<CleanupDialog pending onClose={() => { dismissed = true; }}><p>412300000000 exact bytes</p></CleanupDialog>);
  const dialog = view.getByRole("dialog", { name: "Apply cleanup" });
  expect(dialog.getAttribute("aria-label")).toBe("Apply cleanup");
  expect((view.getByRole("button", { name: "Close" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(dismissed).toBe(false);
  expect(view.getByRole("status").textContent).toContain("Deletion is in progress");
});

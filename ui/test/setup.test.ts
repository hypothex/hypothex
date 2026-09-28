import { expect, test } from "bun:test";

test("happy-dom provides a document", () => {
  const el = document.createElement("p");
  el.textContent = "hi";
  document.body.append(el);
  expect(document.body.querySelector("p")?.textContent).toBe("hi");
  expect(location.origin).toBe("http://127.0.0.1:7777");
});

import { afterEach, expect, test } from "bun:test";
import { cleanup, render } from "@testing-library/react";
import { Unbroken, tokens } from "../../src/pages/components/Headline";
import { PAGES_CSS } from "../../src/pages/components/styles";

afterEach(cleanup);

test("tokens keeps words and the spaces between them", () => {
  expect(tokens("+aug +0.016 over lr 1e-4")).toEqual(["+aug", " ", "+0.016", " ", "over", " ", "lr", " ", "1e-4"]);
  expect(tokens("")).toEqual([]);
});

test("Unbroken wraps each token in a no-wrap span and keeps the text", () => {
  const { container } = render(
    <h1 className="headline">
      <Unbroken text="+aug +0.016 over lr 1e-4 converges higher" />
    </h1>,
  );
  const h1 = container.querySelector("h1");
  expect(h1?.textContent).toBe("+aug +0.016 over lr 1e-4 converges higher");
  const spans = [...(h1?.querySelectorAll("span.nb") ?? [])].map((s) => s.textContent);
  expect(spans).toContain("1e-4");
  expect(spans).toHaveLength(7);
});

test("headline CSS breaks at spaces only", () => {
  expect(PAGES_CSS).toContain(".page h1.headline .nb { white-space: nowrap; }");
  expect(PAGES_CSS).toContain("hyphens: manual; overflow-wrap: normal; word-break: normal;");
});

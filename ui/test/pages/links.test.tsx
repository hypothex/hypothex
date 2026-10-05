import { afterEach, describe, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  AppLink,
  NavigateContext,
  hrefs,
  isAppPath,
  isPlainClick,
  useInAppLinks,
} from "../../src/pages/components/links";

afterEach(cleanup);

describe("hrefs", () => {
  test("builds the contract routes", () => {
    expect(hrefs.overview()).toBe("/");
    expect(hrefs.task("toy-classifier", "toy-test")).toBe("/t/toy-classifier/toy-test");
    expect(hrefs.task("toy-classifier", "toy-test", "overview")).toBe("/t/toy-classifier/toy-test");
    expect(hrefs.task("p", "t", "route-quality")).toBe("/t/p/t?view=route-quality");
    expect(hrefs.edit("p", "t", "new")).toBe("/t/p/t/edit/new");
    expect(hrefs.run("r1", { log: "stderr" })).toBe("/r/r1?log=stderr");
    expect(hrefs.run("r1", { example: "T-014" })).toBe("/r/r1?example=T-014");
    expect(hrefs.examples("A", "B")).toBe("/x/A/B");
    expect(hrefs.examples("A", "B", "accuracy@v1")).toBe("/x/A/B?metric=accuracy%40v1");
  });

  test("encodes every path segment", () => {
    expect(hrefs.run("r 1/2")).toBe("/r/r%201%2F2");
    expect(hrefs.task("my proj", "a/b", "my view")).toBe("/t/my%20proj/a%2Fb?view=my+view");
  });
});

test("isPlainClick rejects modified and non-left clicks", () => {
  const base = { button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false };
  expect(isPlainClick(base)).toBe(true);
  expect(isPlainClick({ ...base, metaKey: true })).toBe(false);
  expect(isPlainClick({ ...base, button: 1 })).toBe(false);
});

describe("AppLink", () => {
  test("navigates in-app on a plain click", () => {
    const navigate = mock((_href: string) => {});
    render(
      <NavigateContext.Provider value={navigate}>
        <AppLink href="/r/r1">run</AppLink>
      </NavigateContext.Provider>,
    );
    const link = screen.getByRole("link", { name: "run" });
    expect(link.getAttribute("href")).toBe("/r/r1");
    const notPrevented = fireEvent.click(link);
    expect(notPrevented).toBe(false);
    expect(navigate).toHaveBeenCalledWith("/r/r1");
  });

  test("leaves the click alone when a handler already prevented it", () => {
    const navigate = mock((_href: string) => {});
    render(
      <NavigateContext.Provider value={navigate}>
        <AppLink href="/r/r1" onClick={(e) => e.preventDefault()}>
          run
        </AppLink>
      </NavigateContext.Provider>,
    );
    fireEvent.click(screen.getByRole("link", { name: "run" }));
    expect(navigate).not.toHaveBeenCalled();
  });
});

describe("useInAppLinks", () => {
  test("routes plain clicks on app links in-app and leaves the rest to the browser", () => {
    expect(["/", "/t/p/t", "/r/r1", "/x/a/b", "/s/p/s-1", "/api/v1/runs", "/mcp", "/rx"].map(isAppPath)).toEqual([
      true,
      true,
      true,
      true,
      true,
      false,
      false,
      false,
    ]);
    const navigate = mock((_href: string) => {});
    const handled: [string, boolean][] = [];
    function Panel() {
      const onLinks = useInAppLinks();
      return (
        // The outer handler records whether the link click was taken over, then stops the
        // test DOM from following the link.
        <div
          onClick={(e) => {
            handled.push([(e.target as HTMLElement).textContent ?? "", e.defaultPrevented]);
            e.preventDefault();
          }}
        >
          <div onClick={onLinks}>
            <a href="/r/r1?example=42">run</a>
            <a href="/api/v1/runs/r1/logs?stream=stderr">raw</a>
            <a href="https://example.com/r/r1">out</a>
            <a href="/r/r2" target="_blank" rel="noreferrer">tab</a>
          </div>
        </div>
      );
    }
    render(
      <NavigateContext.Provider value={navigate}>
        <Panel />
      </NavigateContext.Provider>,
    );
    fireEvent.click(screen.getByRole("link", { name: "run" }));
    fireEvent.click(screen.getByRole("link", { name: "run" }), { metaKey: true });
    for (const name of ["raw", "out", "tab"]) fireEvent.click(screen.getByRole("link", { name }));
    expect(handled).toEqual([
      ["run", true],
      ["run", false],
      ["raw", false],
      ["out", false],
      ["tab", false],
    ]);
    expect(navigate.mock.calls).toEqual([["/r/r1?example=42"]]);
  });
});

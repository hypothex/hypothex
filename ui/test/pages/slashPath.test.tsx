import { afterEach, expect, test } from "bun:test";
import { cleanup, render } from "@testing-library/react";
import { SlashPath } from "../../src/pages/components/SlashPath";

afterEach(cleanup);

test.each(["", "model.pkl", "/", "gpu-a03:/long-project/data set/file-name.json", "/a//b/"])(
  "SlashPath preserves exact text and keeps each segment unbroken: %s",
  (path) => {
    const { container } = render(<SlashPath path={path} className="p" title="full path" />);
    const root = container.firstElementChild as HTMLElement;
    expect(root.tagName).toBe("SPAN");
    expect(root.className).toBe("p");
    expect(root.title).toBe("full path");
    expect(root.textContent).toBe(path);
    expect(root.style.wordBreak).toBe("normal");
    expect(root.style.overflowWrap).toBe("normal");
    expect(root.style.whiteSpace).toBe("normal");
    expect(root.querySelectorAll("wbr")).toHaveLength(path.split("/").length - 1);
    for (const segment of root.querySelectorAll("span")) {
      expect(segment.style.whiteSpace).toBe("nowrap");
    }
    for (const br of root.querySelectorAll("wbr")) {
      expect(br.previousSibling?.textContent?.endsWith("/")).toBe(true);
    }
  },
);

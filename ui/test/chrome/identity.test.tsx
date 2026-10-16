import { describe, expect, test } from "bun:test";
import { render, screen } from "@testing-library/react";
import { AVATAR_HUES, Avatar, avatarHue, initials } from "../../src/chrome/Avatar";
import { EmptyState } from "../../src/chrome/EmptyState";
import { Launcher, launcherKind, launcherName } from "../../src/chrome/Launcher";
import { STATUS_WORD, type StatusKind, StatusIcon } from "../../src/chrome/StatusIcon";

describe("StatusIcon", () => {
  const all: StatusKind[] = ["finished", "running", "queued", "failed", "killed", "lost", "stale"];

  test("every status has its class, a glyph and its word", () => {
    for (const status of all) {
      const { container, unmount } = render(<StatusIcon status={status} />);
      const span = container.querySelector("span.st") as HTMLElement;
      expect([span.className, span.textContent, span.querySelector("svg")?.getAttribute("aria-hidden")]).toEqual([
        `st ${status}`, STATUS_WORD[status], "true",
      ]);
      unmount();
    }
  });

  test("running spins; a custom label replaces the word; icon-only keeps an accessible name", () => {
    const { container } = render(<StatusIcon status="running" label="running 42%" />);
    expect(container.querySelector(".spin")).not.toBeNull();
    expect(container.textContent).toBe("running 42%");
    render(<StatusIcon status="lost" iconOnly title="lost · host gone" />);
    const img = screen.getByRole("img", { name: "lost" });
    expect([img.textContent, img.getAttribute("title")]).toEqual(["", "lost · host gone"]);
  });
});

describe("Launcher", () => {
  test("agent or human glyph, the name after the colon, the full id as title", () => {
    expect([launcherKind("agent:tuner"), launcherKind("human:sam"), launcherKind("human")]).toEqual(["agent", "human", "human"]);
    expect([launcherName("agent:tuner"), launcherName("human"), launcherName("agent:")]).toEqual(["tuner", "human", "agent"]);
    const { container } = render(<Launcher who="agent:tuner" />);
    const span = container.querySelector(".launcher") as HTMLElement;
    expect([span.getAttribute("title"), span.textContent]).toEqual(["agent:tuner", "tuner"]);
    expect(span.querySelector("svg rect")).not.toBeNull();
  });
});

describe("Avatar", () => {
  test("initials and a stable hue per project name", () => {
    expect([initials("rxn-forward"), initials("toy"), initials("retro_agent bench"), initials("")]).toEqual(["RF", "T", "RA", "?"]);
    expect(avatarHue("rxn-forward")).toBe(AVATAR_HUES[0]);
    expect(avatarHue("toy")).toBe(AVATAR_HUES[6]);
    expect(avatarHue("toy")).toBe(avatarHue("toy"));
  });

  test("renders the initials on the hue's tint, decorative next to the name", () => {
    const { container } = render(<Avatar name="rxn-forward" size="sm" />);
    const av = container.querySelector(".av") as HTMLElement;
    expect([av.className, av.textContent, av.getAttribute("aria-hidden")]).toEqual(["av sm", "RF", "true"]);
    expect(av.style.getPropertyValue("--av")).toBe(AVATAR_HUES[0]);
  });
});

describe("EmptyState", () => {
  test("title, body, the first commands and links", () => {
    render(
      <EmptyState
        title="No runs yet"
        body="Hypothex records every run your agents and you launch."
        commands={[
          { n: "1", cmd: "hx init", what: "write hypothex.yaml" },
          { n: "2", cmd: "hx run -- <cmd>", what: "record a run" },
        ]}
        links={[{ label: "Docs", href: "/docs" }]}
      />,
    );
    expect(screen.getByRole("heading", { level: 2, name: "No runs yet" })).not.toBeNull();
    expect([...document.querySelectorAll(".ecmd code")].map((c) => c.textContent)).toEqual(["hx init", "hx run -- <cmd>"]);
    expect(screen.getByRole("link", { name: "Docs" }).getAttribute("href")).toBe("/docs");
  });

  test("loading is a status with a spinner", () => {
    render(<EmptyState loading body="Loading runs…" />);
    expect(screen.getByRole("status").textContent).toBe("Loading runs…");
  });
});

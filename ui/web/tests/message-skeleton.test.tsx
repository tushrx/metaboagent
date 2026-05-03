// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { MessageSkeleton } from "@/components/message-skeleton";

afterEach(() => {
  cleanup();
});

describe("MessageSkeleton", () => {
  it("renders three pulsing bars", () => {
    const { container } = render(<MessageSkeleton />);
    const bars = container.querySelectorAll(".animate-pulse");
    expect(bars.length).toBe(3);
  });

  it("each bar has a different width class", () => {
    const { container } = render(<MessageSkeleton />);
    const bars = Array.from(container.querySelectorAll(".animate-pulse"));
    const widths = bars.map((b) =>
      Array.from(b.classList).find((c) => c.startsWith("w-")),
    );
    // Three distinct widths so the placeholder reads as text-shaped,
    // not a uniform loading bar.
    expect(new Set(widths).size).toBe(3);
  });

  it("exposes a status role for assistive tech", () => {
    const { container } = render(<MessageSkeleton />);
    const status = container.querySelector('[role="status"]');
    expect(status).not.toBeNull();
    expect(status?.getAttribute("aria-label")).toMatch(/preparing|thinking/i);
  });
});

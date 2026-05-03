// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import {
  processChildren,
  renderTextWithPlaceholders,
} from "@/lib/render-text";

afterEach(cleanup);

/**
 * Render the helper's output and inspect the resulting DOM. We render
 * inside a <div> (rather than a <span>) so jsdom's container is happy.
 */
function renderHelper(node: React.ReactNode) {
  return render(<div data-testid="root">{node}</div>);
}

describe("renderTextWithPlaceholders", () => {
  it("returns the input string unchanged when no placeholders are present", () => {
    expect(renderTextWithPlaceholders("plain text")).toBe("plain text");
  });

  it("returns the input string unchanged when input lacks {{ markers", () => {
    expect(renderTextWithPlaceholders("nothing special here")).toBe(
      "nothing special here",
    );
  });

  it("renders K{{SUB:M}} as 'K' + <sub>M</sub>", () => {
    const { container } = renderHelper(
      renderTextWithPlaceholders("K{{SUB:M}}"),
    );
    const sub = container.querySelector("sub");
    expect(sub).not.toBeNull();
    expect(sub!.textContent).toBe("M");
    expect(container.textContent).toBe("KM");
  });

  it("renders {{SUB:M}} at the start of the string", () => {
    const { container } = renderHelper(
      renderTextWithPlaceholders("{{SUB:M}} after"),
    );
    expect(container.querySelector("sub")?.textContent).toBe("M");
    expect(container.textContent).toBe("M after");
  });

  it("renders trailing {{SUP:+}}", () => {
    const { container } = renderHelper(
      renderTextWithPlaceholders("trailing {{SUP:+}}"),
    );
    expect(container.querySelector("sup")?.textContent).toBe("+");
    expect(container.textContent).toBe("trailing +");
  });

  it("renders mixed SUB and SUP placeholders in one string", () => {
    const { container } = renderHelper(
      renderTextWithPlaceholders("{{SUB:M}} and {{SUP:2+}} together"),
    );
    expect(container.querySelector("sub")?.textContent).toBe("M");
    expect(container.querySelector("sup")?.textContent).toBe("2+");
    expect(container.textContent).toBe("M and 2+ together");
  });

  it("leaves a malformed placeholder ({{SUB:M with no close) as text", () => {
    // No closing }} — the regex won't match so the placeholder stays as
    // literal text. This must not crash.
    const out = renderTextWithPlaceholders("foo {{SUB:M and bar");
    expect(out).toBe("foo {{SUB:M and bar");
  });

  it("renders multi-letter SUB content like {{SUB:cat}}", () => {
    const { container } = renderHelper(
      renderTextWithPlaceholders("K{{SUB:cat}}/K{{SUB:M}}"),
    );
    const subs = container.querySelectorAll("sub");
    expect(subs).toHaveLength(2);
    expect(subs[0].textContent).toBe("cat");
    expect(subs[1].textContent).toBe("M");
  });
});

describe("processChildren", () => {
  it("returns null/undefined unchanged", () => {
    expect(processChildren(null)).toBeNull();
    expect(processChildren(undefined)).toBeUndefined();
  });

  it("processes a single string child", () => {
    const { container } = renderHelper(processChildren("K{{SUB:M}} value"));
    expect(container.querySelector("sub")?.textContent).toBe("M");
    expect(container.textContent).toBe("KM value");
  });

  it("processes a mixed array of strings and elements", () => {
    const children = ["start ", <strong key="s">bold</strong>, " end {{SUB:n}}"];
    const { container } = renderHelper(processChildren(children));
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("sub")?.textContent).toBe("n");
    expect(container.textContent).toBe("start bold end n");
  });

  it("leaves non-string non-array children alone", () => {
    const node = <span data-testid="x">hello</span>;
    expect(processChildren(node)).toBe(node);
  });
});

// @vitest-environment jsdom
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CitationRow } from "@/components/evidence-rail";
import type { Citation, CitationKind } from "@/lib/citations";

const writeTextMock = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  writeTextMock.mockClear();
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: writeTextMock },
    configurable: true,
    writable: true,
  });
});

afterEach(() => {
  cleanup();
});

function makeCitation(
  kind: CitationKind,
  id: string,
  provenance: string[] = ["search_kegg"],
): Citation {
  return {
    kind,
    id,
    url: "https://example.test/",
    provenance,
  };
}

async function flushClipboardEffect() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("CitationRow source-type icons", () => {
  // Lucide React stamps each icon with `lucide-<kebab-case>` class so
  // we can assert on which icon was rendered without exporting the
  // CitationIcon component directly.
  const cases: Array<[CitationKind, string]> = [
    ["pmid", "lucide-book-open"],
    ["kegg_compound", "lucide-database"],
    ["kegg_reaction", "lucide-database"],
    ["kegg_ortholog", "lucide-database"],
    ["kegg_pathway", "lucide-database"],
    ["uniprot", "lucide-dna"],
    ["chebi", "lucide-atom"],
    ["doi", "lucide-link-2"],
  ];

  for (const [kind, expectedClass] of cases) {
    it(`renders ${expectedClass} for kind ${kind}`, () => {
      const { container } = render(
        <CitationRow citation={makeCitation(kind, "TESTID")} />,
      );
      expect(container.querySelector(`.${expectedClass}`)).not.toBeNull();
    });
  }
});

describe("CitationRow copy-ID button", () => {
  it("renders the copy button (hidden via opacity until hover)", () => {
    render(<CitationRow citation={makeCitation("kegg_reaction", "R12566")} />);
    const btn = screen.getByLabelText("Copy R12566");
    expect(btn).not.toBeNull();
  });

  it("clicking copy writes citation.id to clipboard", async () => {
    render(<CitationRow citation={makeCitation("pmid", "12345678")} />);
    fireEvent.click(screen.getByLabelText("Copy 12345678"));
    await flushClipboardEffect();
    expect(writeTextMock).toHaveBeenCalledTimes(1);
    expect(writeTextMock).toHaveBeenCalledWith("12345678");
  });

  it("clicking copy does NOT navigate (stopPropagation works)", async () => {
    // The link uses target="_blank" so jsdom's default click handling
    // would trigger a window.open call. We verify here that the copy
    // button click does not bubble to the link by spying on the
    // anchor's `click` directly via event flow assertions.
    render(<CitationRow citation={makeCitation("pmid", "12345")} />);
    const link = screen.getByLabelText(/Open 12345 on/);
    const linkClickSpy = vi.fn();
    link.addEventListener("click", linkClickSpy);

    fireEvent.click(screen.getByLabelText("Copy 12345"));
    await flushClipboardEffect();

    // The copy button's click stops propagation; the link click
    // handler must not have been invoked.
    expect(linkClickSpy).not.toHaveBeenCalled();
    expect(writeTextMock).toHaveBeenCalledTimes(1);
  });
});

describe("CitationRow provenance indicator", () => {
  it("shows '1' for a citation seen in one tool", () => {
    const { container } = render(
      <CitationRow
        citation={makeCitation("pmid", "111", ["fetch_pubmed_live"])}
      />,
    );
    // The wrench is the only `.lucide-wrench` in the row; its sibling
    // span carries the count.
    const wrench = container.querySelector(".lucide-wrench");
    expect(wrench).not.toBeNull();
    const countSpan = wrench!.parentElement!.querySelector("span");
    expect(countSpan?.textContent).toBe("1");
  });

  it("shows '2' when provenance has two entries", () => {
    const { container } = render(
      <CitationRow
        citation={makeCitation("kegg_compound", "C00022", [
          "search_kegg",
          "fetch_kegg_live",
        ])}
      />,
    );
    const wrench = container.querySelector(".lucide-wrench");
    expect(wrench!.parentElement!.querySelector("span")?.textContent).toBe(
      "2",
    );
  });

  it("shows '3' when provenance has three entries", () => {
    const { container } = render(
      <CitationRow
        citation={makeCitation("doi", "10.1000/xyz", ["a", "b", "c"])}
      />,
    );
    const wrench = container.querySelector(".lucide-wrench");
    expect(wrench!.parentElement!.querySelector("span")?.textContent).toBe(
      "3",
    );
  });

  it("title attribute carries the full provenance list", () => {
    const { container } = render(
      <CitationRow
        citation={makeCitation("pmid", "999", [
          "search_pubmed",
          "fetch_pubmed_live",
        ])}
      />,
    );
    // The wrench wrapper span carries the `title`.
    const wrench = container.querySelector(".lucide-wrench");
    const wrapper = wrench!.parentElement!;
    expect(wrapper.getAttribute("title")).toBe(
      "from search_pubmed, fetch_pubmed_live",
    );
  });
});

describe("CitationRow link", () => {
  it("renders an <a> covering the card with the right href", () => {
    render(
      <CitationRow
        citation={{
          kind: "kegg_reaction",
          id: "R12566",
          url: "https://www.kegg.jp/entry/R12566",
          provenance: ["search_kegg"],
        }}
      />,
    );
    const link = screen.getByLabelText(/Open R12566 on/);
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe(
      "https://www.kegg.jp/entry/R12566",
    );
    expect(link.getAttribute("target")).toBe("_blank");
  });
});

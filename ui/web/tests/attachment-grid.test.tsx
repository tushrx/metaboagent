// @vitest-environment jsdom
/* eslint-disable @next/next/no-img-element */
import React from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AttachmentGrid } from "@/components/message-list";
import { Lightbox } from "@/components/lightbox";
import type { Attachment } from "@/lib/api";

afterEach(cleanup);

function makeAttachment(name: string): Attachment {
  return {
    kind: "image",
    mime_type: "image/png",
    filename: name,
    // Tiny valid-ish base64; jsdom never decodes it, we only check src/alt.
    data_base64: "iVBORw0KGgo=",
    thumbnail_base64: "iVBORw0KGgo=",
  };
}

describe("AttachmentGrid", () => {
  it("renders one thumbnail button per attachment", () => {
    render(
      <AttachmentGrid
        attachments={[makeAttachment("a.png"), makeAttachment("b.png")]}
      />,
    );
    const imgs = screen.getAllByRole("img");
    expect(imgs.length).toBe(2);
    expect(imgs[0].getAttribute("alt")).toBe("a.png");
    expect(imgs[1].getAttribute("alt")).toBe("b.png");
  });

  it("opens a lightbox dialog when a thumbnail is clicked", () => {
    render(<AttachmentGrid attachments={[makeAttachment("zoomed.png")]} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /preview zoomed\.png/i }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-label")).toMatch(/zoomed\.png/);
  });
});

describe("Lightbox", () => {
  it("invokes onClose when the Escape key is pressed", () => {
    let closed = 0;
    render(
      <Lightbox
        attachment={makeAttachment("esc-test.png")}
        onClose={() => {
          closed += 1;
        }}
      />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(closed).toBe(1);
  });
});

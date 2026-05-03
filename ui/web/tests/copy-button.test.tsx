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
import { MessageList, type ChatMessage } from "@/components/message-list";

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

function makeAssistant(content: string): ChatMessage {
  return { id: "asst-1", role: "assistant", content };
}

function makeUser(content: string): ChatMessage {
  return { id: "user-1", role: "user", content };
}

/**
 * Wait for `navigator.clipboard.writeText` (returned promise) to resolve
 * and React to flush the resulting state update. We do it via a
 * microtask flush wrapped in `act` rather than `waitFor` so the assertion
 * is deterministic — there's nothing async to poll for in a unit test.
 */
async function flushClipboardEffect() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("MessageList copy buttons", () => {
  it("renders a copy button on assistant messages", () => {
    render(
      <MessageList
        messages={[makeAssistant("Hello, this is the answer.")]}
        streaming={null}
      />,
    );
    expect(screen.queryByLabelText("Copy message")).not.toBeNull();
  });

  it("does NOT render a copy button on user messages", () => {
    render(
      <MessageList messages={[makeUser("My question.")]} streaming={null} />,
    );
    expect(screen.queryByLabelText("Copy message")).toBeNull();
  });

  it("does NOT render a copy button on canceled assistant messages", () => {
    const msg: ChatMessage = {
      id: "asst-c",
      role: "assistant",
      content: "partial",
      canceled: true,
    };
    render(<MessageList messages={[msg]} streaming={null} />);
    expect(screen.queryByLabelText("Copy message")).toBeNull();
  });

  it("clicking the message copy writes the raw markdown content", async () => {
    const content = "**Hello** with $K_M$ math and `inline code`.";
    render(
      <MessageList messages={[makeAssistant(content)]} streaming={null} />,
    );
    fireEvent.click(screen.getByLabelText("Copy message"));
    await flushClipboardEffect();
    expect(writeTextMock).toHaveBeenCalledTimes(1);
    expect(writeTextMock).toHaveBeenCalledWith(content);
  });

  it("button title flips from 'Copy' to 'Copied!' after click and reverts after 1.5s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(
      <MessageList
        messages={[makeAssistant("Some answer text.")]}
        streaming={null}
      />,
    );
    const btn = screen.getByLabelText("Copy message");
    expect(btn.getAttribute("title")).toBe("Copy");

    fireEvent.click(btn);
    await flushClipboardEffect();
    expect(btn.getAttribute("title")).toBe("Copied!");

    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    expect(btn.getAttribute("title")).toBe("Copy");
    vi.useRealTimers();
  });

  it("renders a code-block copy button for fenced code", () => {
    const content = "Here is a snippet:\n\n```js\nconsole.log(1);\n```";
    render(
      <MessageList messages={[makeAssistant(content)]} streaming={null} />,
    );
    expect(screen.queryByLabelText("Copy code")).not.toBeNull();
  });

  it("does NOT render a code copy button for inline `code`", () => {
    const content = "Use the `console.log` function.";
    render(
      <MessageList messages={[makeAssistant(content)]} streaming={null} />,
    );
    expect(screen.queryByLabelText("Copy code")).toBeNull();
  });

  it("clicking code-block copy writes the code text to clipboard", async () => {
    const content = "```js\nconsole.log(42);\n```";
    render(
      <MessageList messages={[makeAssistant(content)]} streaming={null} />,
    );
    fireEvent.click(screen.getByLabelText("Copy code"));
    await flushClipboardEffect();
    expect(writeTextMock).toHaveBeenCalledTimes(1);
    const arg = writeTextMock.mock.calls[0][0] as string;
    expect(arg).toContain("console.log(42);");
  });
});

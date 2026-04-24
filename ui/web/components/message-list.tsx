"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Wrench, AlertCircle, XCircle } from "lucide-react";
import type { ToolCallEvent } from "@/lib/api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallEvent[];
  error?: string;
  canceled?: boolean;
}

export interface StreamingState {
  /** Accumulated assistant text for the in-flight response. */
  text: string;
  /** Tool calls emitted during the current turn. */
  toolCalls: ToolCallEvent[];
  /** ID for the message currently being streamed (for aria-live etc.). */
  id: string;
}

interface Props {
  messages: ChatMessage[];
  streaming: StreamingState | null;
  onToolCrumbClick?: (toolCallId: string) => void;
}

export function MessageList({ messages, streaming, onToolCrumbClick }: Props) {
  // Scroll control lives in the MainPane parent now — it owns the
  // scrollable viewport. We just render content.
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-8">
      {messages.map((m) => (
        <MessageRow key={m.id} message={m} onToolCrumbClick={onToolCrumbClick} />
      ))}
      {streaming && (
        <StreamingRow state={streaming} onToolCrumbClick={onToolCrumbClick} />
      )}
    </div>
  );
}

function MessageRow({
  message,
  onToolCrumbClick,
}: {
  message: ChatMessage;
  onToolCrumbClick?: (id: string) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-blue-50 px-4 py-2.5 text-[15px] text-gray-900">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {message.toolCalls && message.toolCalls.length > 0 && (
        <ToolCrumbStrip
          toolCalls={message.toolCalls}
          onClick={onToolCrumbClick}
        />
      )}
      <AssistantProse content={message.content} />
      {message.canceled && (
        <div className="flex items-center gap-1.5 text-sm text-gray-500">
          <XCircle size={14} />
          <span>Canceled</span>
        </div>
      )}
      {message.error && (
        <div className="flex items-center gap-1.5 text-sm text-red-600">
          <AlertCircle size={14} />
          <span>{message.error}</span>
        </div>
      )}
    </div>
  );
}

function StreamingRow({
  state,
  onToolCrumbClick,
}: {
  state: StreamingState;
  onToolCrumbClick?: (id: string) => void;
}) {
  return (
    <div
      className="flex flex-col gap-2"
      aria-live="polite"
      aria-label="Assistant response (streaming)"
    >
      {state.toolCalls.length > 0 && (
        <ToolCrumbStrip
          toolCalls={state.toolCalls}
          onClick={onToolCrumbClick}
        />
      )}
      {state.text ? (
        <AssistantProse content={state.text} />
      ) : (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-gray-400" />
          <span>Thinking…</span>
        </div>
      )}
    </div>
  );
}

/**
 * Inline bread-crumb row that points at the tool-activity cards in the
 * evidence rail. Small, muted, clickable — not the primary display.
 */
function ToolCrumbStrip({
  toolCalls,
  onClick,
}: {
  toolCalls: ToolCallEvent[];
  onClick?: (id: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {toolCalls.map((tc) => (
        <button
          key={tc.id}
          type="button"
          onClick={() => onClick?.(tc.id)}
          className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 font-mono text-[11px] text-gray-500 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"
          title={`Jump to ${tc.name} in the evidence rail`}
        >
          <Wrench size={10} />
          {tc.name}
        </button>
      ))}
    </div>
  );
}

function AssistantProse({ content }: { content: string }) {
  return (
    <div className="prose-assistant text-[15px] leading-7 text-gray-900">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: (props) => <p className="my-3 first:mt-0 last:mb-0" {...props} />,
          ul: (props) => <ul className="my-3 list-disc pl-6" {...props} />,
          ol: (props) => <ol className="my-3 list-decimal pl-6" {...props} />,
          li: (props) => <li className="my-1" {...props} />,
          h1: (props) => (
            <h1 className="mt-5 mb-2 text-lg font-semibold" {...props} />
          ),
          h2: (props) => (
            <h2 className="mt-4 mb-2 text-[17px] font-semibold" {...props} />
          ),
          h3: (props) => (
            <h3 className="mt-3 mb-1.5 text-[15px] font-semibold" {...props} />
          ),
          code: ({ className, children, ...rest }) => {
            const isInline = !(className && className.startsWith("language-"));
            if (isInline) {
              return (
                <code
                  className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[13px] text-gray-900"
                  {...rest}
                >
                  {children}
                </code>
              );
            }
            return (
              <code className="font-mono text-[13px]" {...rest}>
                {children}
              </code>
            );
          },
          pre: (props) => (
            <pre
              className="my-3 overflow-x-auto rounded-lg bg-gray-900 p-3 text-gray-100"
              {...props}
            />
          ),
          a: (props) => (
            <a
              className="text-blue-600 underline underline-offset-2 hover:text-blue-700"
              target="_blank"
              rel="noopener noreferrer"
              {...props}
            />
          ),
          hr: () => <hr className="my-4 border-gray-200" />,
          strong: (props) => <strong className="font-semibold" {...props} />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

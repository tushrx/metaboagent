"use client";

import type { ChatMessage, StreamingState } from "./message-list";
import { MessageList } from "./message-list";
import { InputArea, type InputAreaHandle } from "./input-area";
import { SuggestedPrompts } from "./suggested-prompts";
import type { Ref } from "react";

interface Props {
  messages: ChatMessage[];
  streaming: StreamingState | null;
  input: string;
  onInputChange: (next: string) => void;
  onSubmit: () => void;
  onAbort: () => void;
  onPickPrompt: (prompt: string) => void;
  onRetry: () => void;
  lastError: string | null;
  inputRef: Ref<InputAreaHandle>;
  onToolCrumbClick?: (toolCallId: string) => void;
}

export function MainPane({
  messages,
  streaming,
  input,
  onInputChange,
  onSubmit,
  onAbort,
  onPickPrompt,
  onRetry,
  lastError,
  inputRef,
  onToolCrumbClick,
}: Props) {
  const isEmpty = messages.length === 0 && !streaming;

  return (
    <section
      className="flex min-w-0 flex-1 flex-col bg-white"
      aria-label="Chat"
    >
      <div className="flex-1 overflow-y-auto">
        {isEmpty ? (
          <SuggestedPrompts onPick={onPickPrompt} />
        ) : (
          <MessageList
            messages={messages}
            streaming={streaming}
            onToolCrumbClick={onToolCrumbClick}
          />
        )}
      </div>

      {lastError && !streaming && (
        <div className="mx-auto w-full max-w-3xl px-6">
          <div className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            <span>{lastError}</span>
            <button
              type="button"
              onClick={onRetry}
              className="ml-3 rounded-md border border-red-300 bg-white px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      <InputArea
        ref={inputRef}
        value={input}
        onChange={onInputChange}
        onSubmit={onSubmit}
        onAbort={onAbort}
        streaming={!!streaming}
      />
    </section>
  );
}

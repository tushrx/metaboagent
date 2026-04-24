"use client";

import { Send, StopCircle } from "lucide-react";
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
} from "react";

const MAX_ROWS = 8;

export interface InputAreaHandle {
  /** Programmatic focus (used when a suggested prompt is clicked). */
  focus: () => void;
}

interface Props {
  value: string;
  onChange: (next: string) => void;
  onSubmit: () => void;
  onAbort: () => void;
  streaming: boolean;
  disabled?: boolean;
}

export const InputArea = forwardRef<InputAreaHandle, Props>(function InputArea(
  { value, onChange, onSubmit, onAbort, streaming, disabled = false },
  ref,
) {
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const rowHeight = useRef<number>(0);

  useImperativeHandle(ref, () => ({
    focus: () => taRef.current?.focus(),
  }));

  // Measure the natural line-height once so auto-grow can cap at MAX_ROWS.
  useEffect(() => {
    const el = taRef.current;
    if (!el || rowHeight.current) return;
    const cs = window.getComputedStyle(el);
    const lh = parseFloat(cs.lineHeight);
    if (!Number.isNaN(lh) && lh > 0) rowHeight.current = lh;
  }, []);

  // Auto-grow up to MAX_ROWS, then scroll internally.
  useLayoutEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    const lh = rowHeight.current || 24;
    const max = lh * MAX_ROWS;
    const next = Math.min(el.scrollHeight, max);
    el.style.height = `${next}px`;
    el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
  }, [value]);

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Ctrl+Enter (or Cmd+Enter on macOS) → submit. Plain Enter = newline.
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (!streaming && !disabled && value.trim()) onSubmit();
    }
  }

  const canSend = !streaming && !disabled && value.trim().length > 0;

  return (
    <div className="border-t border-gray-200 bg-white">
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2 px-6 py-4">
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKey}
          disabled={streaming || disabled}
          placeholder="Ask about a pathway, compound, enzyme… (Ctrl+Enter to send)"
          rows={1}
          aria-label="Message input"
          className="min-h-[44px] flex-1 resize-none rounded-2xl border border-gray-200 bg-white px-4 py-2.5 text-[15px] leading-6 text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 disabled:bg-gray-50 disabled:text-gray-500"
        />

        {streaming ? (
          <button
            type="button"
            onClick={onAbort}
            aria-label="Abort response"
            className="flex h-[44px] w-[44px] shrink-0 items-center justify-center rounded-full bg-red-600 text-white transition-colors hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500/40"
            title="Abort (current response will stop)"
          >
            <StopCircle size={18} />
          </button>
        ) : (
          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSend}
            aria-label="Send message"
            className="flex h-[44px] w-[44px] shrink-0 items-center justify-center rounded-full bg-blue-600 text-white transition-colors hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500/40 disabled:bg-gray-200 disabled:text-gray-400"
            title="Send (Ctrl+Enter)"
          >
            <Send size={18} />
          </button>
        )}
      </div>
    </div>
  );
});

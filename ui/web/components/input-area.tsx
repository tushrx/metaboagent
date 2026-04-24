"use client";

import { Paperclip, Send, StopCircle, X } from "lucide-react";
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
} from "react";
import type { Attachment } from "@/lib/api";

const MAX_ROWS = 8;
export const MAX_ATTACHMENTS = 3;

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
  attachments: Attachment[];
  onSelectFiles: (files: File[]) => void;
  onRemoveAttachment: (index: number) => void;
}

export const InputArea = forwardRef<InputAreaHandle, Props>(function InputArea(
  {
    value,
    onChange,
    onSubmit,
    onAbort,
    streaming,
    disabled = false,
    attachments,
    onSelectFiles,
    onRemoveAttachment,
  },
  ref,
) {
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const rowHeight = useRef<number>(0);

  useImperativeHandle(ref, () => ({
    focus: () => taRef.current?.focus(),
  }));

  useEffect(() => {
    const el = taRef.current;
    if (!el || rowHeight.current) return;
    const cs = window.getComputedStyle(el);
    const lh = parseFloat(cs.lineHeight);
    if (!Number.isNaN(lh) && lh > 0) rowHeight.current = lh;
  }, []);

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
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (!streaming && !disabled && canSubmit) onSubmit();
    }
  }

  function handleFilePick(e: React.ChangeEvent<HTMLInputElement>) {
    const list = e.target.files;
    if (list && list.length > 0) onSelectFiles(Array.from(list));
    // Reset so selecting the same filename twice still fires onChange.
    e.target.value = "";
  }

  const hasText = value.trim().length > 0;
  const hasAttachments = attachments.length > 0;
  const canSubmit = hasText || hasAttachments;
  const canSend = !streaming && !disabled && canSubmit;
  const attachDisabled =
    streaming || disabled || attachments.length >= MAX_ATTACHMENTS;

  return (
    <div className="border-t border-gray-200 bg-white">
      <div className="mx-auto w-full max-w-3xl px-6 py-4">
        {hasAttachments && (
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {attachments.map((att, i) => (
              <AttachmentThumb
                key={`${att.filename}-${i}`}
                attachment={att}
                onRemove={() => onRemoveAttachment(i)}
              />
            ))}
            <span className="text-[12px] text-gray-500">
              {attachments.length} {attachments.length === 1 ? "image" : "images"} attached
            </span>
          </div>
        )}

        <div className="flex items-end gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            className="hidden"
            onChange={handleFilePick}
            aria-hidden="true"
            tabIndex={-1}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={attachDisabled}
            aria-label={
              attachments.length >= MAX_ATTACHMENTS
                ? `Attachment limit reached (${MAX_ATTACHMENTS})`
                : "Attach image"
            }
            title={
              attachments.length >= MAX_ATTACHMENTS
                ? `Maximum ${MAX_ATTACHMENTS} images per message`
                : "Attach an image (PNG, JPEG, WebP)"
            }
            className="flex h-[44px] w-[44px] shrink-0 items-center justify-center rounded-full text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
          >
            <Paperclip size={18} />
          </button>

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
    </div>
  );
});

function AttachmentThumb({
  attachment,
  onRemove,
}: {
  attachment: Attachment;
  onRemove: () => void;
}) {
  const src = `data:${attachment.mime_type};base64,${attachment.thumbnail_base64}`;
  return (
    <div className="relative">
      {/* eslint-disable-next-line @next/next/no-img-element -- data: URI; next/image doesn't apply */}
      <img
        src={src}
        alt={attachment.filename}
        title={attachment.filename}
        className="h-16 w-16 rounded-md border border-gray-200 object-cover"
      />
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${attachment.filename}`}
        className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full border border-gray-200 bg-white text-gray-600 shadow-sm transition-colors hover:bg-red-600 hover:text-white"
      >
        <X size={12} />
      </button>
    </div>
  );
}

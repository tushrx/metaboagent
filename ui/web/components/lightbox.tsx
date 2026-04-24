"use client";

import { X } from "lucide-react";
import { useEffect } from "react";
import type { Attachment } from "@/lib/api";

interface Props {
  attachment: Attachment;
  onClose: () => void;
}

/**
 * Minimal full-screen preview for an image attachment. Click the
 * backdrop or hit Esc to close. When the full-resolution blob has
 * been dropped (e.g. after a localStorage restore), we fall back to
 * the thumbnail and show a small caption.
 */
export function Lightbox({ attachment, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  const full = attachment.data_base64;
  const src = full
    ? `data:${attachment.mime_type};base64,${full}`
    : `data:${attachment.mime_type};base64,${attachment.thumbnail_base64}`;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Preview of ${attachment.filename}`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close preview"
        className="absolute right-4 top-4 flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20"
      >
        <X size={18} />
      </button>
      <div
        className="relative flex max-h-full max-w-full flex-col items-center gap-2"
        onClick={(e) => e.stopPropagation()}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- data: URI; next/image doesn't apply */}
        <img
          src={src}
          alt={attachment.filename}
          className="max-h-[85vh] max-w-full rounded-md object-contain shadow-lg"
        />
        <div className="flex flex-col items-center gap-0.5 text-[12px] text-white/80">
          <span>{attachment.filename}</span>
          {!full && (
            <span className="text-white/60">
              Full resolution unavailable after page reload.
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

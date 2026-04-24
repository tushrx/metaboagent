"use client";

import { X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";

type ToastTone = "info" | "error";

interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

interface ToastCtx {
  push: (message: string, tone?: ToastTone) => void;
}

const Ctx = createContext<ToastCtx | null>(null);

export function useToast(): ToastCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useToast must be used inside <ToastProvider>");
  return v;
}

const TOAST_TIMEOUT_MS = 6000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (message: string, tone: ToastTone = "error") => {
      const id = nextId.current++;
      setToasts((prev) => [...prev, { id, message, tone }]);
      setTimeout(() => dismiss(id), TOAST_TIMEOUT_MS);
    },
    [dismiss],
  );

  return (
    <Ctx.Provider value={{ push }}>
      {children}
      <div
        className="pointer-events-none fixed right-4 top-4 z-50 flex w-[min(360px,calc(100vw-2rem))] flex-col gap-2"
        aria-live="polite"
        aria-atomic="false"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`pointer-events-auto flex items-start justify-between gap-3 rounded-md border px-3 py-2 text-[13px] shadow-md ${
              t.tone === "error"
                ? "border-red-200 bg-red-50 text-red-900"
                : "border-gray-200 bg-white text-gray-800"
            }`}
          >
            <span className="break-words">{t.message}</span>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className="shrink-0 text-gray-500 transition-colors hover:text-gray-900"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

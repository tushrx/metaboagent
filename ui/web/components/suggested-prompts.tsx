"use client";

import { ArrowRight } from "lucide-react";

const SAMPLES: readonly string[] = [
  "How is artemisinin produced biotechnologically?",
  "Look up KEGG compound C00022 and summarize its pathways.",
  "Find recent PubMed papers on lycopene biosynthesis in yeast.",
];

interface Props {
  onPick: (prompt: string) => void;
}

export function SuggestedPrompts({ onPick }: Props) {
  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col items-center justify-center px-6">
      <h2 className="mb-1 text-[22px] font-semibold tracking-tight text-gray-900">
        Where should we start?
      </h2>
      <p className="mb-7 text-sm text-gray-500">
        Pick a starting prompt or type your own. Ctrl+Enter to send.
      </p>

      <ul className="flex w-full flex-col gap-2.5" aria-label="Suggested prompts">
        {SAMPLES.map((prompt) => (
          <li key={prompt}>
            <button
              type="button"
              onClick={() => onPick(prompt)}
              className="group flex w-full items-center justify-between rounded-xl border border-gray-200 bg-white px-4 py-3 text-left text-[15px] text-gray-800 transition-all duration-150 ease-out hover:-translate-y-px hover:border-blue-300 hover:bg-blue-50 hover:shadow-sm focus:border-blue-400 focus:bg-blue-50 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
            >
              <span>{prompt}</span>
              <ArrowRight
                size={16}
                className="ml-3 shrink-0 text-gray-400 transition-all duration-150 ease-out group-hover:translate-x-0.5 group-hover:text-blue-600"
              />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

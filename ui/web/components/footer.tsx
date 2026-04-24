import { Code2, BookOpen } from "lucide-react";

const GITHUB_URL =
  "https://github.com/tusharmicro/metaboagent";
const DOCS_URL =
  "https://github.com/tusharmicro/metaboagent/tree/main/docs";

export function Footer() {
  return (
    <footer className="border-t border-gray-100 bg-white px-6 py-2.5 text-[11px] text-gray-500">
      <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center justify-between gap-2">
        <span>
          Built at Homi Bhabha State University for the Gemma 4 Good
          Hackathon · May 2026
        </span>
        <div className="flex items-center gap-3">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 hover:text-gray-900"
            aria-label="GitHub repository (opens in new tab)"
          >
            <Code2 size={11} />
            GitHub
          </a>
          <a
            href={DOCS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 hover:text-gray-900"
            aria-label="Documentation (opens in new tab)"
          >
            <BookOpen size={11} />
            Docs
          </a>
        </div>
      </div>
    </footer>
  );
}

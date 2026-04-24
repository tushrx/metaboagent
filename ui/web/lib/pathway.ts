/**
 * Pathway extraction from assistant final_answer markdown.
 *
 * The system prompt instructs the agent to render pathway steps in
 * exactly this shape (CLAUDE.md §4 / agent/prompts/__init__.py):
 *
 *     Step 1: <substrate> → <product>
 *         Reaction: <KEGG R-id>   EC <x.x.x.x>
 *         Enzyme: <name> (<organism>)   PMID:<id>
 *
 * We parse line-by-line with a tiny state machine. Metadata lines are
 * optional in any combination; the arrow can be Unicode → or ASCII ->.
 *
 * Multiple pathways in a single answer are detected by a second "Step 1"
 * reset; we truncate to the *first* pathway to keep linear rendering
 * simple. (Future phases can return all pathways for branched diagrams.)
 */

export interface PathwayEnzyme {
  name: string;
  organism?: string;
}

export interface PathwayStep {
  index: number;
  substrate: string;
  product: string;
  reaction?: string;
  ec?: string;
  enzyme?: PathwayEnzyme;
  pmid?: string;
}

export interface PathwayData {
  steps: PathwayStep[];
  /** ID of the assistant message this pathway was extracted from. */
  source_message_id: string;
}

// --- Line patterns -------------------------------------------------------

const STEP_RE =
  /^Step\s+(\d+)[:.]?\s*(.+?)\s*(?:→|->|-->)\s*(.+?)\s*$/i;
const REACTION_ID_RE = /\b(R\d{5})\b/;
const EC_RE = /\b(?:EC[:\s]*)?(\d+\.\d+\.\d+\.\d+)\b/i;
const ENZYME_RE =
  /^Enzyme[:\s]+(.+?)(?:\s*\(([^)]+)\))?\s*(?:PMID[:\s]*(\d+))?\s*$/i;
const PMID_RE = /\bPMID[:\s]*(\d+)\b/i;

// --- Extraction ----------------------------------------------------------

/**
 * Map known non-Unicode arrow renderings to the plain → the parser wants.
 * Despite the system prompt telling the model to use →, Gemma 4 is fond
 * of emitting ``$\rightarrow$`` inside scientific prose. Rather than
 * widen the regex or duplicate arrow alternatives (which makes the
 * grammar harder to reason about), we normalize at the input boundary.
 * This is a pre-parser character substitution, not parser permissiveness.
 */
function normalizeArrows(content: string): string {
  return content
    .replace(/\$\\rightarrow\$/g, "→") //  $\rightarrow$ (LaTeX inline)
    .replace(/\\rightarrow\b/g, "→") //   \rightarrow (raw LaTeX)
    .replace(/&rarr;/gi, "→") //          HTML entity
    .replace(/[⟶➡]/g, "→"); //            heavy arrows
}

export function extractPathway(
  content: string,
  sourceMessageId: string,
): PathwayData {
  const lines = normalizeArrows(content).split(/\r?\n/);
  const steps: PathwayStep[] = [];
  let current: PathwayStep | null = null;
  let truncated = false;

  const flush = () => {
    if (current) {
      steps.push(current);
      current = null;
    }
  };

  for (const raw of lines) {
    if (truncated) break;
    const line = raw.trim();
    if (!line) continue;

    const stepMatch = STEP_RE.exec(line);
    if (stepMatch) {
      const idx = parseInt(stepMatch[1], 10);
      // A second "Step 1" after we already have steps means a new
      // pathway block. Truncate to the first.
      if (idx === 1 && steps.length > 0) {
        flush();
        truncated = true;
        break;
      }
      flush();
      current = {
        index: idx,
        substrate: cleanLabel(stepMatch[2]),
        product: cleanLabel(stepMatch[3]),
      };
      continue;
    }

    if (!current) continue;

    // Metadata lines (any order, all optional).
    if (/^Reaction[:\s]/i.test(line)) {
      const r = REACTION_ID_RE.exec(line);
      if (r) current.reaction = r[1];
      const e = EC_RE.exec(line);
      if (e) current.ec = e[1];
      continue;
    }
    if (/^Enzyme[:\s]/i.test(line)) {
      const m = ENZYME_RE.exec(line);
      if (m) {
        current.enzyme = { name: m[1].trim() };
        if (m[2]) current.enzyme.organism = m[2].trim();
        if (m[3] && !current.pmid) current.pmid = m[3];
      }
      continue;
    }
    // Stand-alone PMID line (or trailing bit on any metadata line).
    const p = PMID_RE.exec(line);
    if (p && !current.pmid) current.pmid = p[1];
  }
  flush();

  return { steps, source_message_id: sourceMessageId };
}

function cleanLabel(s: string): string {
  // Strip stray markdown emphasis / code-fence chars; preserve content.
  return s
    .replace(/^[*_`\s]+|[*_`\s]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Phase-1 plan extraction.
 *
 * The agent emits a `<plan>...</plan>` block in Phase 1 of the design
 * flow with 3-4 candidate approaches. The shape inside the tag varies
 * because Gemma 4 doesn't always honour the system-prompt example:
 *
 *   1. Bare JSON array — `[{...}, {...}]`
 *   2. Object with `approaches` key — `{"target": ..., "approaches": [...]}`
 *   3. NDJSON-style — multiple `{...}` blocks separated by newlines, no
 *      outer brackets at all.
 *
 * `extractPlan` accepts all three. Anything else — malformed JSON,
 * missing `<plan>` tag, partial-stream `<plan>` without a close — is
 * treated as "no plan" and the original text is returned untouched.
 */

export interface PlanOption {
  id: string;
  title: string;
  route?: string;
  host?: string;
  summary: string;
  est_difficulty?: string;
  est_confidence?: number;
}

export interface ExtractPlanResult {
  plan: PlanOption[] | null;
  textWithoutPlan: string;
}

const PLAN_TAG_RE = /<plan>([\s\S]*?)<\/plan>/i;

export function extractPlan(text: string): ExtractPlanResult {
  if (!text) return { plan: null, textWithoutPlan: text };

  const m = PLAN_TAG_RE.exec(text);
  if (!m) return { plan: null, textWithoutPlan: text };

  const inner = m[1].trim();
  if (!inner) return { plan: null, textWithoutPlan: text };

  const approaches = parseApproaches(inner);
  if (approaches === null) {
    // Malformed JSON inside <plan>: keep the raw block so a developer
    // can still see the agent's output. Surface a console warning.
    if (typeof console !== "undefined") {
      console.warn("[plan.extractPlan] could not parse plan JSON:", inner);
    }
    return { plan: null, textWithoutPlan: text };
  }

  const plan = approaches
    .map(toPlanOption)
    .filter((p): p is PlanOption => p !== null);
  if (plan.length === 0) return { plan: null, textWithoutPlan: text };

  // Strip exactly the matched <plan>...</plan> block (the regex has no
  // /g flag, so this only removes the first occurrence — defensive
  // against the rare case of two blocks).
  const textWithoutPlan = text.replace(PLAN_TAG_RE, "").trim();
  return { plan, textWithoutPlan };
}

function parseApproaches(inner: string): unknown[] | null {
  // Form 1 + 2: whole block parses as JSON.
  try {
    const parsed = JSON.parse(inner);
    if (Array.isArray(parsed)) return parsed;
    if (
      parsed &&
      typeof parsed === "object" &&
      Array.isArray((parsed as { approaches?: unknown }).approaches)
    ) {
      return (parsed as { approaches: unknown[] }).approaches;
    }
  } catch {
    // fall through to form 3
  }

  // Form 3: NDJSON-style — pull out balanced `{...}` blocks and parse
  // each. Safer than splitting on newlines because a single object can
  // span multiple lines.
  const objs = findJsonObjects(inner);
  if (objs.length === 0) return null;

  const out: unknown[] = [];
  for (const s of objs) {
    try {
      out.push(JSON.parse(s));
    } catch {
      return null;
    }
  }
  return out;
}

/** Walk `text` and return every balanced `{...}` substring. */
function findJsonObjects(text: string): string[] {
  const results: string[] = [];
  let depth = 0;
  let start = -1;
  let inStr = false;
  let escape = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (escape) {
      escape = false;
      continue;
    }
    if (inStr) {
      if (c === "\\") escape = true;
      else if (c === '"') inStr = false;
      continue;
    }
    if (c === '"') {
      inStr = true;
      continue;
    }
    if (c === "{") {
      if (depth === 0) start = i;
      depth++;
    } else if (c === "}") {
      depth--;
      if (depth === 0 && start !== -1) {
        results.push(text.slice(start, i + 1));
        start = -1;
      }
    }
  }
  return results;
}

function toPlanOption(item: unknown): PlanOption | null {
  if (!item || typeof item !== "object") return null;
  const o = item as Record<string, unknown>;
  if (typeof o.id !== "string" || typeof o.title !== "string") return null;
  return {
    id: o.id,
    title: o.title,
    route: typeof o.route === "string" ? o.route : undefined,
    host: typeof o.host === "string" ? o.host : undefined,
    summary: typeof o.summary === "string" ? o.summary : "",
    est_difficulty:
      typeof o.est_difficulty === "string" ? o.est_difficulty : undefined,
    est_confidence:
      typeof o.est_confidence === "number" ? o.est_confidence : undefined,
  };
}

/**
 * Render a plan as markdown. Returned string can be concatenated with
 * any preceding prose and fed straight into ReactMarkdown.
 */
export function formatPlanAsMarkdown(plan: PlanOption[]): string {
  const lines: string[] = ["**Approaches**", ""];
  for (const p of plan) {
    const meta: string[] = [];
    if (p.route) meta.push(p.route);
    if (p.host) meta.push(p.host);
    if (p.est_difficulty) meta.push(`${p.est_difficulty} difficulty`);
    if (p.est_confidence !== undefined) {
      meta.push(`${p.est_confidence} confidence`);
    }
    const metaSuffix = meta.length > 0 ? `  (${meta.join(" · ")})` : "";
    lines.push(`**${p.id}. ${p.title}**${metaSuffix}`);
    if (p.summary) lines.push(p.summary);
    lines.push("");
  }
  const ids = plan.map((p) => p.id);
  let idList: string;
  if (ids.length === 1) idList = ids[0];
  else if (ids.length === 2) idList = `${ids[0]} or ${ids[1]}`;
  else idList = `${ids.slice(0, -1).join(", ")}, or ${ids[ids.length - 1]}`;
  lines.push(`*Reply with ${idList} to continue with that approach.*`);
  return lines.join("\n");
}

/**
 * Serialize a PathwayData object into Mermaid `flowchart LR` syntax.
 *
 *   flowchart LR
 *     N0("acetyl-CoA")
 *     N1("acetoacetyl-CoA")
 *     N0 -->|"acetoacetyl-CoA thiolase<br/>EC 2.3.1.9"| N1
 *     ...
 *
 * Nodes chain linearly (N0 → N1 → N2 → …) because the agent's pathway
 * format is the linear substrate → product chain documented in the
 * system prompt. Each edge is labeled with the enzyme name and EC
 * number when available; otherwise a plain arrow.
 */
import type { PathwayData, PathwayStep } from "./pathway";

export function pathwayToMermaid(pathway: PathwayData): string {
  if (pathway.steps.length === 0) return "";

  const lines: string[] = ["flowchart LR"];
  const steps = pathway.steps;

  // Emit the leading node (substrate of the first step), then one node
  // per product. Substrate of step N+1 is product of step N, so we
  // don't need to re-emit it.
  lines.push(`  N0(${quote(cleanNode(steps[0].substrate))})`);
  for (let i = 0; i < steps.length; i++) {
    const step = steps[i];
    const fromId = `N${i}`;
    const toId = `N${i + 1}`;
    lines.push(`  ${toId}(${quote(cleanNode(step.product))})`);
    const label = edgeLabel(step);
    if (label) {
      lines.push(`  ${fromId} -->|${quote(label)}| ${toId}`);
    } else {
      lines.push(`  ${fromId} --> ${toId}`);
    }
  }
  return lines.join("\n");
}

function edgeLabel(step: PathwayStep): string {
  const bits: string[] = [];
  if (step.enzyme?.name) bits.push(cleanEdge(step.enzyme.name));
  if (step.ec) bits.push(`EC ${step.ec}`);
  // Mermaid uses <br/> inside quoted labels for line breaks.
  return bits.join("<br/>");
}

/** Escape chars that would break a Mermaid quoted node/edge label. */
function cleanNode(s: string): string {
  return s.replace(/"/g, "'").replace(/\|/g, "／");
}

function cleanEdge(s: string): string {
  // Edge labels: Mermaid breaks on | and " even inside pipes.
  return s.replace(/"/g, "'").replace(/\|/g, "／");
}

function quote(s: string): string {
  return `"${s}"`;
}

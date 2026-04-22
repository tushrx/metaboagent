"""
Phase 7 — rule library skeleton.

A structured, retrievable corpus of scientific heuristics that sit *alongside*
the evidence layer (papers, pathway docs) and the entity layer (molecules,
enzymes, organisms). codex_rag_design.md §13 calls out four rule families:
host selection, enzyme prioritization, pathway heuristics, troubleshooting.
We keep chemistry-comparison rules as a fifth family so chem/bio route-tradeoff
heuristics have a home.

What this module is:
- A typed schema (:class:`Rule`, :class:`RuleCategory`, :class:`RuleScope`)
  consistent with the Phase 4/5/6 dataclass style.
- A small in-memory repository (:class:`RuleRepository`) with category /
  scope / applies_to / free-text filters.
- A seed list of representative rules so tests and downstream prototypes have
  real content to work with.

What this module is **not** (anti-scope, per phase brief):
- A rule engine. Nothing here evaluates, chains, or fires rules — callers
  *retrieve* rules and let the agent decide what to do with them.
- A DSL. Rules are plain structured dicts (text + metadata). If/when a
  formal condition grammar is needed, it slots into ``Rule.conditions`` in
  ``extras`` without breaking this API.
- Wired into the agent. Existing ReAct tools continue to work unchanged.
  Opting in = ``from agent.rag import default_rule_repository``.

Extension pattern:
- Add rules: append to ``_SEED_RULES`` (or build a ``RuleRepository`` from
  your own source — YAML/DB/LLM-generated).
- Add categories: extend :class:`RuleCategory`. Existing rules keep working.
- Add filter axes: extend :meth:`RuleRepository.search` with new keyword
  arguments; the core API stays stable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional


# ---------- taxonomy ----------
class RuleCategory(str, Enum):
    """Top-level rule family (codex_rag_design.md §13)."""
    HOST_SELECTION = "host_selection"
    ENZYME_PRIORITIZATION = "enzyme_prioritization"
    PATHWAY_HEURISTIC = "pathway_heuristic"
    TROUBLESHOOTING = "troubleshooting"
    CHEMISTRY_COMPARISON = "chemistry_comparison"


class RuleScope(str, Enum):
    """How specifically the rule is scoped to a subject.

    GENERAL — applies regardless of host/molecule/pathway. Most heuristics.
    HOST — applies only when the named chassis/organism is in play.
    PATHWAY — applies only within the named pathway/class.
    ENZYME — applies to the named EC / enzyme class.
    MOLECULE — applies to the named molecule / molecule class.
    """
    GENERAL = "general"
    HOST = "host"
    PATHWAY = "pathway"
    ENZYME = "enzyme"
    MOLECULE = "molecule"


class EvidenceBasis(str, Enum):
    """Where this rule came from. Parallels the 'output labels' in
    codex_plan.md §6 (Confirmed/Supported/Inference/Hypothesis) so the
    agent can surface the same trust tier.
    """
    DATABASE = "database"            # extracted from KEGG/UniProt/etc.
    LITERATURE = "literature"        # distilled from papers
    EXPERT_HEURISTIC = "expert_heuristic"   # domain convention, uncited
    HYPOTHESIS = "hypothesis"        # model- or user-generated, unvalidated


# ---------- Rule dataclass ----------
@dataclass(frozen=True)
class Rule:
    """One retrievable scientific heuristic.

    Fields mirror the Phase 4/5/6 entity convention: primary ID, stable
    metadata, text body, free-form ``extras``. Deliberate omissions: no
    ``conditions`` AST, no ``action`` hook — those belong to a future rule
    engine, not this skeleton. If you need them, stash them in ``extras``
    so this schema stays frozen.
    """
    rule_id: str                                # e.g. "host.terpene_mva_yeast"
    category: RuleCategory
    scope: RuleScope
    text: str                                   # the rule, one or two sentences
    rationale: Optional[str] = None             # *why* this rule exists
    confidence: float = 0.5                     # 0.0 – 1.0
    evidence_basis: EvidenceBasis = EvidenceBasis.EXPERT_HEURISTIC

    # ``applies_to`` uses scoped-id strings so retrieval can filter by prefix.
    # Examples: "chassis:ecoli", "pathway:MEP", "molecule_class:terpenoid",
    # "ec:2.5.1.29". Anything before the colon is the axis; anything after is
    # the value. Values are case-insensitive during lookup.
    applies_to: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    # Citation metadata — loose strings by design; Phase 3/4 citation
    # verification will cross-check these against our evidence collections.
    citations: tuple[str, ...] = ()
    source: str = "seed"                        # "seed" | "curated" | "llm" | ...
    extras: dict = field(default_factory=dict, compare=False)


# ---------- repository ----------
class RuleRepository:
    """In-memory rule store with simple filter + keyword search.

    Intentionally boring: a list + a handful of index dicts built once at
    construction. No pagination, no ranking beyond category-tiebreaker
    confidence-descending ordering. Replace with a DB-backed implementation
    later without changing the public API.
    """

    def __init__(self, rules: Optional[Iterable[Rule]] = None):
        self._rules: list[Rule] = list(rules) if rules is not None else []
        self._index_by_id: dict[str, Rule] = {r.rule_id: r for r in self._rules}
        if len(self._index_by_id) != len(self._rules):
            # Detect duplicate rule_ids early — config errors are easier to
            # fix at load time than when a retrieval silently returns the
            # wrong variant.
            seen: set[str] = set()
            for r in self._rules:
                if r.rule_id in seen:
                    raise ValueError(
                        f"duplicate rule_id in repository: {r.rule_id!r}"
                    )
                seen.add(r.rule_id)

    # ---------- basic accessors ----------
    def __len__(self) -> int:
        return len(self._rules)

    def __iter__(self):
        return iter(self._rules)

    def all(self) -> list[Rule]:
        return list(self._rules)

    def by_id(self, rule_id: str) -> Optional[Rule]:
        return self._index_by_id.get(rule_id)

    def by_category(self, category: RuleCategory) -> list[Rule]:
        return self.search(category=category)

    def by_applies_to(self, token: str) -> list[Rule]:
        return self.search(applies_to=token)

    # ---------- search ----------
    def search(
        self,
        query: Optional[str] = None,
        *,
        category: Optional[RuleCategory] = None,
        scope: Optional[RuleScope] = None,
        applies_to: Optional[str] = None,
        tag: Optional[str] = None,
        min_confidence: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> list[Rule]:
        """Filter rules by any combination of axes.

        ``query`` is a case-insensitive substring match across
        ``rule_id``/``text``/``rationale``/``tags``. Not a semantic search —
        semantic retrieval over rule text belongs in the evidence layer
        (embed rules into a vector collection) and is explicitly out of
        scope for this skeleton.

        ``applies_to`` accepts either a full token (``"chassis:ecoli"``) or
        an axis prefix (``"chassis:"``). Matching is case-insensitive.

        Results are ordered (category, scope, -confidence, rule_id) — stable
        and deterministic so tests and UI layouts don't flicker.
        """
        q = query.lower().strip() if query else None
        at = applies_to.lower().strip() if applies_to else None
        tg = tag.lower().strip() if tag else None

        hits: list[Rule] = []
        for r in self._rules:
            if category is not None and r.category is not category:
                continue
            if scope is not None and r.scope is not scope:
                continue
            if min_confidence is not None and r.confidence < min_confidence:
                continue
            if tg is not None and not any(t.lower() == tg for t in r.tags):
                continue
            if at is not None and not _applies_to_matches(r.applies_to, at):
                continue
            if q is not None and not _keyword_matches(r, q):
                continue
            hits.append(r)

        hits.sort(key=_rule_sort_key)
        if limit is not None:
            hits = hits[: max(0, int(limit))]
        return hits


# ---------- helpers ----------
_WORD_RE = re.compile(r"[a-z0-9]+")


def _applies_to_matches(applies_to: tuple[str, ...], needle: str) -> bool:
    """Match ``needle`` against an entry in ``applies_to``.

    Rules:
    - If ``needle`` contains ``:`` it's treated as a full token (exact, case-
      insensitive match).
    - If ``needle`` ends with ``:`` it's treated as an axis prefix and we
      return True for any entry on that axis.
    - Otherwise we match the value side (after ``:``) case-insensitively.
    """
    needle = needle.lower()
    for entry in applies_to:
        e = entry.lower()
        if needle.endswith(":"):
            if e.startswith(needle):
                return True
        elif ":" in needle:
            if e == needle:
                return True
        else:
            axis, _, value = e.partition(":")
            if value == needle or axis == needle:
                return True
    return False


def _keyword_matches(rule: Rule, q: str) -> bool:
    haystacks = [
        rule.rule_id,
        rule.text,
        rule.rationale or "",
        " ".join(rule.tags),
        " ".join(rule.applies_to),
    ]
    blob = " ".join(haystacks).lower()
    # AND across whitespace-separated terms so multi-word queries narrow down
    # rather than OR-expand.
    terms = [t for t in _WORD_RE.findall(q) if t]
    if not terms:
        return True
    return all(term in blob for term in terms)


def _rule_sort_key(r: Rule) -> tuple:
    # Category order as declared on the enum, then scope order, then
    # higher confidence first, then stable-tiebreak on rule_id.
    return (
        list(RuleCategory).index(r.category),
        list(RuleScope).index(r.scope),
        -float(r.confidence),
        r.rule_id,
    )


# ---------- seed rules ----------
# Representative, not exhaustive. Each captures a heuristic from
# codex_rag_design.md §13 or general metabolic engineering practice. Keep
# texts short and self-contained — the agent will render them verbatim.
_SEED_RULES: list[Rule] = [
    Rule(
        rule_id="host.terpene_mva_prefers_yeast",
        category=RuleCategory.HOST_SELECTION,
        scope=RuleScope.GENERAL,
        text=(
            "For terpenoid targets where mevalonate-pathway flux dominates, "
            "Saccharomyces cerevisiae is often preferred over E. coli due to "
            "native MVA activity and better P450 support."
        ),
        rationale=(
            "Yeast natively runs the MVA pathway and has ER membrane for "
            "P450-coupled hydroxylations; E. coli uses MEP and has weaker "
            "eukaryotic P450 expression."
        ),
        confidence=0.80,
        evidence_basis=EvidenceBasis.LITERATURE,
        applies_to=("molecule_class:terpenoid", "pathway:MVA", "chassis:scerevisiae"),
        tags=("host", "terpenoid", "p450", "mva"),
        citations=("PMID:16612385",),  # Ro et al., artemisinic acid in yeast
    ),
    Rule(
        rule_id="host.rapid_iteration_prefers_ecoli",
        category=RuleCategory.HOST_SELECTION,
        scope=RuleScope.GENERAL,
        text=(
            "When rapid iteration and simple cloning matter more than "
            "eukaryotic post-translational machinery, E. coli is typically "
            "the default chassis."
        ),
        rationale=(
            "E. coli has fast growth, mature molecular-biology toolkit, and "
            "large library of characterized parts."
        ),
        confidence=0.85,
        evidence_basis=EvidenceBasis.EXPERT_HEURISTIC,
        applies_to=("chassis:ecoli",),
        tags=("host", "iteration", "cloning"),
    ),
    Rule(
        rule_id="enzyme.prefer_host_literature_precedent",
        category=RuleCategory.ENZYME_PRIORITIZATION,
        scope=RuleScope.GENERAL,
        text=(
            "Prioritize enzymes with published functional expression in the "
            "intended host over orthologs with only in-vitro or native-organism "
            "characterization."
        ),
        rationale=(
            "Folding, codon use, cofactor availability, and toxicity often "
            "derail orthologs that look good on paper. Prior heterologous "
            "success de-risks those failure modes."
        ),
        confidence=0.85,
        evidence_basis=EvidenceBasis.EXPERT_HEURISTIC,
        applies_to=(),
        tags=("enzyme", "ranking", "heterologous"),
    ),
    Rule(
        rule_id="enzyme.penalize_membrane_when_host_support_weak",
        category=RuleCategory.ENZYME_PRIORITIZATION,
        scope=RuleScope.GENERAL,
        text=(
            "Down-weight membrane-bound or multi-cofactor enzymes (e.g. P450s "
            "requiring CPR partners, iron-sulfur cluster assemblies) when the "
            "host lacks robust support for the required machinery."
        ),
        rationale=(
            "Heterologous membrane and cofactor-complex enzymes fail commonly "
            "unless the host has matching ER/partner proteins; flagging this "
            "upfront avoids wasted rounds of cloning."
        ),
        confidence=0.75,
        evidence_basis=EvidenceBasis.EXPERT_HEURISTIC,
        applies_to=(),
        tags=("enzyme", "membrane", "p450", "cofactor"),
    ),
    Rule(
        rule_id="pathway.minimize_heterologous_step_count",
        category=RuleCategory.PATHWAY_HEURISTIC,
        scope=RuleScope.GENERAL,
        text=(
            "Prefer routes that require the fewest heterologous steps over "
            "the host's native metabolism; each extra foreign enzyme adds "
            "expression, cofactor, and toxicity risk."
        ),
        rationale=(
            "Strain-design failure modes scale roughly linearly with the "
            "number of introduced genes — balance elegance against build cost."
        ),
        confidence=0.85,
        evidence_basis=EvidenceBasis.EXPERT_HEURISTIC,
        applies_to=(),
        tags=("pathway", "minimal", "step_count"),
    ),
    Rule(
        rule_id="pathway.prefer_native_precursor_availability",
        category=RuleCategory.PATHWAY_HEURISTIC,
        scope=RuleScope.GENERAL,
        text=(
            "Favor pathway entry points whose immediate precursor is already "
            "abundant in the chosen host's central metabolism."
        ),
        rationale=(
            "Boosting a native precursor (e.g., acetyl-CoA, FPP, chorismate) "
            "is usually cheaper and more predictable than building the "
            "precursor supply from scratch."
        ),
        confidence=0.80,
        evidence_basis=EvidenceBasis.EXPERT_HEURISTIC,
        applies_to=(),
        tags=("pathway", "precursor", "flux"),
    ),
    Rule(
        rule_id="pathway.check_cofactor_consistency",
        category=RuleCategory.PATHWAY_HEURISTIC,
        scope=RuleScope.GENERAL,
        text=(
            "Verify that oxidoreductase steps in the proposed route use "
            "cofactors (NADH vs NADPH, FAD, PLP) that the host can supply; "
            "mismatched cofactor demand is a common silent bottleneck."
        ),
        rationale=(
            "A pathway that net-consumes NADPH in a host that is NADH-rich "
            "will stall even with expressed enzymes."
        ),
        confidence=0.75,
        evidence_basis=EvidenceBasis.EXPERT_HEURISTIC,
        applies_to=(),
        tags=("pathway", "cofactor", "redox"),
    ),
    Rule(
        rule_id="troubleshoot.precursor_accumulation_implies_downstream_bottleneck",
        category=RuleCategory.TROUBLESHOOTING,
        scope=RuleScope.GENERAL,
        text=(
            "If a metabolic intermediate accumulates while the final product "
            "is low, the rate-limiting step is downstream of that intermediate."
        ),
        rationale=(
            "Intermediate pooling is a direct signal of kinetic imbalance; "
            "focus optimization on the enzyme consuming that intermediate."
        ),
        confidence=0.85,
        evidence_basis=EvidenceBasis.EXPERT_HEURISTIC,
        applies_to=(),
        tags=("troubleshooting", "bottleneck", "flux"),
    ),
    Rule(
        rule_id="troubleshoot.expressed_but_no_product",
        category=RuleCategory.TROUBLESHOOTING,
        scope=RuleScope.GENERAL,
        text=(
            "If the target enzyme is detectably expressed but the product is "
            "absent, investigate folding, missing cofactor, or transport/"
            "sequestration before changing the coding sequence."
        ),
        rationale=(
            "Abundant but inactive protein typically indicates a post-"
            "translational failure mode rather than an expression problem."
        ),
        confidence=0.80,
        evidence_basis=EvidenceBasis.EXPERT_HEURISTIC,
        applies_to=(),
        tags=("troubleshooting", "folding", "cofactor", "transport"),
    ),
    Rule(
        rule_id="chem_vs_bio.route_comparison_axes",
        category=RuleCategory.CHEMISTRY_COMPARISON,
        scope=RuleScope.GENERAL,
        text=(
            "Compare biological and chemical routes on six axes: feedstock "
            "cost, step count, selectivity, scale, waste/E-factor, and "
            "purification burden. A single-axis comparison is misleading."
        ),
        rationale=(
            "Microbial routes often win on feedstock and selectivity but lose "
            "on titer/productivity; chemical routes often win on rate but "
            "lose on regioselectivity and waste."
        ),
        confidence=0.80,
        evidence_basis=EvidenceBasis.EXPERT_HEURISTIC,
        applies_to=(),
        tags=("chemistry", "comparison", "tradeoff", "green_chemistry"),
    ),
]


def default_rule_repository() -> RuleRepository:
    """Return a repository backed by :data:`_SEED_RULES`.

    Safe to call multiple times — the object is cheap to build. Swap in a
    different source (YAML on disk, DB-backed, LLM-curated) by constructing
    ``RuleRepository(rules=...)`` directly.
    """
    return RuleRepository(_SEED_RULES)

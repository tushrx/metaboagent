# MetaboAgent — Day 2 Report (2026-04-20)

> Single-file recap of everything changed today, why it was changed, the bugs
> we caught along the way, and the priorities for tonight. Read this first
> before restarting work.

---

## 1. Session context

- **Starting state**: Day 1 shipped on 2026-04-15 with the full agent live at
  `:7860`, 3/3 demo scenarios passing, ChromaDB populated with 54 k docs.
  PubMed corpus was expanded to 52 k on Day 2 (2026-04-17) but the UI
  priorities (showcase dropdown, pathway viz) were still untouched as of this
  morning.
- **Session goal (as requested)**:
  1. Add the showcase-mode dropdown / demo presets so judges can see
     expected-vs-generated side-by-side.
  2. Expand the knowledge base beyond the 3 scripted demos — any molecule
     the user asks about should work.
  3. Add a *plan → user approves → deep dive* two-phase flow.
  4. Wire real open-web search (DuckDuckGo, no API key required).
  5. Make the chat feel like ChatGPT — no lag, clean bubbles, live progress.
  6. Fix visibility bugs (white text on white background, narrow column).
- **vLLM status**: still running Gemma 4 31B-IT on `:8000`, no restart
  performed today (so manual ReAct loop is still the active path).

---

## 2. What shipped today

### 2.1 Showcase preset chips (Task #1–3)

- Added three clickable preset chips below the header: **Artemisinic acid**,
  **Taxadiene**, **Vanillin** — each with its own `tagline`, query, and an
  `expected` block (target / host / pathway / key enzymes / reference PMIDs).
- Clicking a chip fires the agent immediately with the preset query and
  injects a yellow **"reference · published strain"** card *above* the
  generated answer so the user can visually compare MetaboAgent's output to
  the literature-validated strain.
- References used: Ro 2006 (PMID 16612385), Paddon 2013 (PMID 23575629),
  Ajikumar 2010 Science (PMID 20929886), Hansen 2009 (PMID 19201962).
- **Files**: `ui/app.py`
  (`SHOWCASE_SCENARIOS` dict, `_render_reference_card`, `on_showcase`),
  `ui/theme.py` (`.showcase-chip`, `.reference-card*` CSS).

### 2.2 Light-mode fix + wider layout (Task #4)

- The UI was rendering white text on white background because Gradio 6 was
  auto-detecting OS dark mode and applying `html.dark` overrides.
- Forced `color-scheme: light` on `html`, `html.dark`, `body`, `body.dark`;
  added aggressive `.dark .chat-thread *` colour overrides; also instructed
  users to append `?__theme=light` to the URL as a belt-and-braces fallback.
- Container widened `820px → 1200px` with `width: 100%` so longer messages
  don't wrap awkwardly. Chat region height raised from `64–78vh` to
  `72–82vh` so more history is visible at once.
- **Files**: `ui/theme.py`.

### 2.3 Streaming trace — two iterations (Task #5 then Task #10)

- **First pass**: surfaced every thought and tool call as a live card in the
  assistant bubble so the UI would stop appearing blank for 20–60 s while the
  agent ran. Each event rendered as its own mini-card with label, body,
  observation, and a pulsing 3-dot spinner.
- **Second pass (ChatGPT-style)**: the cards felt noisy. Collapsed to a
  **single-line "thinking…"** indicator with a `show steps` `<details>`
  accordion for the full trace. Status swaps between *thinking* / *reasoning*
  / *searching · \<tool\>* as the agent progresses.
- Added **yield throttling**: the UI refreshes at most every ~400 ms
  (`_YIELD_THROTTLE_SECS = 0.4`) instead of on every event, killing the
  re-render spam that caused the laggy feel.
- After the final answer is rendered, a separate collapsed "reasoning trace"
  `<details>` keeps the tool-call list accessible for audit.
- **Files**: `ui/app.py` (`_render_progress`, `_collapse_trace`,
  `_run_agent`), `ui/theme.py` (`.trace`, `.trace-head`, `.trace-details`,
  `.reasoning-trace` CSS).

### 2.4 Open-web search via DuckDuckGo (Task #7)

- New tool `agent/tools/web_search.py`:
  `@tool web_search(query, max_results=5)`. Uses the `ddgs` 9.x package
  (with fallback to legacy `duckduckgo_search` 8.x) — **no API key**.
- Wired into `agent/metabo_agent.py`: imports, `build_tools()` registry,
  ReAct instructions, and the `Action:` enum line.
- System-prompt guidance: "use for industrial / commercial strain reports,
  patent summaries, green-chemistry case studies, or general chemistry
  refs outside PubMed."
- Live-smoke-tested against `vanillin biosynthesis review` → returned
  Wikipedia + phenylpropanoid pages with valid titles/URLs.

### 2.5 Plan-then-approve two-phase flow (Tasks #8 + #9)

This is the **biggest behavioural change of the day**. Every "make X /
produce X / design a strain for X / synthesize X" request now goes through:

**Phase 1 — Propose.**
- Agent does ≤ 3 tool calls (typically `search_kegg`, `fetch_pubchem`,
  maybe `web_search`) for a *light* evidence sweep — no deep pathway work.
- Emits Final Answer as 2–4 sentences of context + a `<plan>…</plan>` JSON
  block with **3–4 candidate approaches**: usually one microbial in
  *S. cerevisiae* (MVA), one microbial in *E. coli* (MEP/shikimate), one
  chemical total-synthesis route, and one hybrid.
- Each approach carries `id`, `title`, `route`, `host`, one-line `summary`,
  `est_difficulty`, and `est_confidence`.
- **Does NOT produce pathway steps, plasmid maps, or confidence scores yet.**

**Phase 2 — Deep dive.**
- When the user replies selecting an approach (either clicking an approach
  button or typing "A" / "go with option B"), the agent produces the
  full blueprint: pathway, host rationale, modifications, confidence.
- System prompt explicitly says Phase 2 must **reuse** Phase 1 evidence
  rather than re-querying.

**Conversational queries bypass the flow.** Questions like "what is
phenylpropanoid?" or "explain MVA" get direct prose answers — the `<plan>`
block only triggers for *executable* design requests.

- **Files**: `agent/prompts/system_prompt.py` (new `# Two-phase flow` and
  `# Conversational / explanatory questions bypass the two-phase flow`
  sections).

### 2.6 Plan-card rendering + approach-selector buttons (Task #9 again)

- `ui/app.py` parses `<plan>` block out of the agent's Final Answer via
  `_parse_plan` → `_render_plan_card` renders a 2×2 grid of cards with
  badges (route, host, difficulty, confidence) in the assistant bubble.
- Gradio chatbots can't catch clicks on HTML inside a bubble, so **four
  real `gr.Button` "plan action" pills** live below the chat. A `gr.State`
  named `plan_state` tracks the current plan; after each agent response
  the buttons update their labels and visibility via
  `_plan_button_updates(plan)`.
- Clicking a plan button fires `on_plan_select(index, …)` which submits
  "Proceed with approach X: \<title\>. Run the full design — pathway, host
  rationale, modifications, and confidence."
- **Files**: `ui/app.py` (plan parsing, `_render_plan_card`,
  `_plan_button_updates`, `on_plan_select`, rewired handlers to output
  `[chatbot, user_input, plan_state, *plan_buttons]`).

### 2.7 UI smoothness pass (Task #10 recap)

Beyond what's above, the **`on_submit` / `on_showcase` / `on_plan_select`**
handlers were refactored into one shared generator `_run_agent(user_msg,
chat_history, *, preamble=None)`. Single source of truth for event
streaming, throttling, plan-state plumbing, and final rendering. Less
duplication, easier to debug.

### 2.8 Multi-turn history bug (discovered during testing)

The user reported the agent responding with "I have already provided the
answers to your questions." — on second-turn interactions the agent
thought it had already answered. Two compounding bugs:

1. **Off-by-one in history slicing**: `agent_history = chat_history[:
   -(1 + len(preamble))]` included the current user turn, so the LLM saw
   the query twice (once in history, once as the fresh `HumanMessage`).
   **Fix**: compute history from `prior_history` (the list *before* we
   appended the current turn) — safe, correct, off-by-one-proof.
2. **HTML leaked into LLM history**: prior assistant turns were fed
   verbatim to the LLM, including their `<plan>{…}</plan>` blocks,
   `<details>` reasoning traces, and `<div class="trace">` scaffolding.
   The model saw its own UI plumbing and concluded "I already answered."
   **Fix**: new `_clean_assistant_for_history(text)` in `agent/metabo_agent.py`
   strips `<plan>` blocks, `<plasmid-map>`, `<compare-table>`, `<div>`,
   and `<details>` blocks in entirety, then removes any remaining HTML
   tags, before wrapping into `AIMessage`. Verified: the scaffolded
   input `<div class="trace">...</div>\nHere is a plan for vanillin:\n<plan>{…}</plan>\nPick one.\n<details>…</details>`
   round-trips to `"Here is a plan for vanillin:\n\nPick one."`.
- **Files**: `ui/app.py` (`_run_agent`), `agent/metabo_agent.py`
  (`_HTML_TAG_RE`, `_PLAN_BLOCK_RE`, `_DROP_BLOCK_RE`,
  `_clean_assistant_for_history`, updated `_build_history_messages`).

---

## 3. Files changed today

| File | Purpose |
|---|---|
| `ui/app.py` | Showcase chips, plan parser/renderer, plan action buttons, shared `_run_agent` generator, ChatGPT-style trace indicator, HTML history fix |
| `ui/theme.py` | Forced light mode, widened container, styled showcase chips + reference card + plan cards + plan action pills + new trace CSS |
| `agent/tools/web_search.py` | **New** — DuckDuckGo `@tool web_search` |
| `agent/tools/__init__.py` | (no change — package auto-collects; `metabo_agent` imports submodule directly) |
| `agent/metabo_agent.py` | Imports + registers `web_search`, ReAct instructions updated, `Action:` enum expanded, added `_clean_assistant_for_history` and wired it into `_build_history_messages` |
| `agent/prompts/system_prompt.py` | Added `# Two-phase flow for "make X" requests` section and `# Conversational / explanatory questions bypass the two-phase flow` section |
| `day_report_2026-04-20.md` | **This file** |

Nothing in `data/`, `vectorstore/`, or `scripts/` was touched today.

---

## 4. Bug fixes applied today (do not reintroduce)

1. **White-on-white text** — Gradio 6 auto-detected OS dark mode and applied
   `html.dark` overrides on top of our CSS. Fix: aggressively override
   `.dark` class and force `color-scheme: light` at the `html` level.
2. **Narrow 820px column** — widened to 1200px with `width: 100%`. Matches
   chat-bubble widths used by ChatGPT / Claude.
3. **Blank-until-done streaming** — the previous `on_submit` set
   `chat_history[-1]["content"] = "…"` on every event, never surfacing
   anything. Fixed by building a running `steps` list and rendering it
   through `_render_progress`.
4. **Gradio refresh spam** — yield-per-event overwhelmed the frontend.
   Throttled to ~400 ms.
5. **Agent says "I already answered"** — off-by-one + HTML-leak, fixed as
   described above.
6. **Plan-button click doesn't fire** — Gradio chat HTML can't be wired
   to event handlers inline, so use real `gr.Button`s below the chat with
   `plan_state`-driven visibility.

---

## 5. Known issues / still to verify tonight

- [ ] **End-to-end plan→approve flow on a novel molecule** — ran unit-level
      smoke tests (web_search live query, HTML strip test, UI HTTP 200) but
      did NOT run a full "make aspirin → click A → deep dive" through the
      browser after the history-bug fix. **Do this first tonight.**
- [ ] **Phase-1 discipline** — Gemma is instructed to stop after emitting
      `<plan>`, but it may still sneak in pathway prose. Watch for it and
      tighten the prompt if so ("You MUST stop and output the plan block
      without producing numbered pathway steps in Phase 1").
- [ ] **Phase-2 discipline** — after an approach is selected, Gemma should
      NOT emit another `<plan>` block. Watch for this; add an explicit
      "DO NOT emit <plan> in Phase 2" rule if it misbehaves.
- [ ] **Chat context length** — multi-turn chats where Phase 1 + Phase 2 +
      follow-ups all accumulate could hit token limits. `LLM_MAX_TOKENS`
      is in `config.py`; check whether history summarisation is needed.
- [ ] **DuckDuckGo rate limiting** — if the agent hits DDG several times
      in a single session it may get throttled. `web_search` handles this
      gracefully (returns `{"error": "...", "results": []}`) but we
      haven't exercised it under load.
- [ ] **Showcase chip + plan interaction** — the showcase chips bypass the
      plan flow (they go straight to deep dive via the reference card).
      Decide: should showcase also go through the plan flow for
      consistency? Currently NO, because the reference card already
      shows the expected approach. Leave as-is unless it confuses judges.
- [ ] **Browser refresh without "New chat"** — after restarting UI the
      user should click "New chat" first; a stale `plan_state` from a
      prior session could make old buttons appear. Mostly cosmetic.

---

## 6. Tonight's priorities (in order)

### A. Verify today's work end-to-end
1. Reload `http://localhost:<port>/?__theme=light`.
2. Click **New chat**.
3. Try a novel molecule: **"make paracetamol"** or **"design a strain for
   mevalonate"**. Expect: plan card + 4 approach buttons below.
4. Click approach **A**. Expect: full pathway + host + modifications +
   confidence. **No** "I already answered" message.
5. Ask a follow-up: **"why that host?"** — should stay conversational,
   no plan card, no button update.
6. Try a conversational query: **"what is the MEP pathway?"** — should
   get direct prose, no plan card.

### B. Tighten what we have before adding more
- Review `agent/prompts/system_prompt.py` after a few real runs. Common
  failure modes to look for: emitting pathway steps in Phase 1, waffling
  between approaches in Phase 2, re-issuing the same tool query 3–4×.
- If plan-selector buttons look cramped on mobile, tweak `.plan-action-row`
  CSS to wrap instead of fighting for horizontal space.

### C. Original day-2 priorities still pending
1. **Pathway visualisation** (priority #2 from Day 1, still untouched) —
   post-process blueprint steps into a NetworkX DAG → render as inline
   Mermaid HTML or SVG. Biggest remaining judge-visible uplift.
2. **Citation verification post-processor** — for every PMID / KEGG ID
   the agent cites, confirm it exists in the indexed collection; strip
   or flag hallucinations. Kills the "is this real?" objection.
3. **Verify PubMed expansion is queryable** — `literature.jsonl` is
   52 k rows but nobody has confirmed ChromaDB's `literature` collection
   actually has all of them indexed. Count with a quick retriever query.
4. **BRENDA kinetics for `rank_enzymes`** — current scoring is
   heuristic; real kcat / Km would land the catalytic-efficiency story.
5. **Drop manual ReAct loop** — request vLLM restart with
   `--enable-auto-tool-choice --tool-call-parser hermes`. Cuts latency
   and unlocks native structured outputs.
6. **Exercise the 9 secondary tools** — `design_primers`,
   `design_expression_vector`, `fetch_uniprot`, `fetch_sabio_rk`, etc.
   are wired into the agent but probably not hit in a typical flow.
   Write a smoke test that forces each one through a canonical query
   so we know none of them are silently broken.

### D. Nice-to-haves
- **Plan card on the showcase chips too** — make all three routes to the
  deep dive go through the same UI path. Less cognitive load.
- **Export / share a run** — button to copy the final Markdown +
  citations so judges can paste into a doc.
- **Query history sidebar** — past conversations clickable, ChatGPT-style.
  Low priority but visible polish.

---

## 7. How to run tonight

```bash
cd /home/tusharmicro/metaboagent

# 0. Confirm vLLM is up
curl -s -H "Authorization: Bearer $VLLM_API_KEY" http://localhost:8000/v1/models

# 1. (If the UI isn't already running) launch it in the background
PYTHONPATH=/home/tusharmicro/metaboagent nohup python3 -m scripts.run_ui \
    > /home/tusharmicro/metaboagent/logs/ui_showcase.log 2>&1 &

# 2. Confirm :7860 is listening
ss -ltn | grep 7860

# 3. From your laptop, forward a free local port
ssh -N -L 9000:localhost:7860 <user>@<server>

# 4. Open the UI — force light mode on first load
#    http://localhost:9000/?__theme=light

# 5. For CLI sanity:
PYTHONPATH=/home/tusharmicro/metaboagent python3 -m scripts.run_agent \
    "Design a strain to produce mevalonate"
```

**Current UI PID** is in `/home/tusharmicro/metaboagent/logs/ui_showcase.log`
(grep for `Running on`). To kill and restart: `pkill -f scripts.run_ui`.

---

## 8. Summary for your future self

Today turned the agent from "demo-scripted" into "ask anything":

- **Before today**: 3 hard-coded demo scenarios were the only things that
  worked cleanly; any new molecule got a grab-bag response with no
  structure; UI was narrow, laggy, and sometimes unreadable.
- **After today**: any molecule goes through Phase 1 (plan with 3–4
  approaches — microbial, chemical, hybrid) → user clicks one →
  Phase 2 deep dive. Open web search fills gaps beyond PubMed. The UI
  is wider, light-mode-locked, smoothly streaming, ChatGPT-styled,
  and no longer confuses itself on multi-turn because prior HTML is
  stripped from the LLM's view.

**The single most important verification for tonight** is the end-to-end
flow in §6.A. If that works on a molecule none of the demo scripts know
about, everything else we did today was real and the system has genuinely
generalised.

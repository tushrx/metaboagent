"""
MetaboAgent theme — minimal white single-column chat (ChatGPT/Claude-style).

No sidebar, no dashboard widgets. A centered conversation column on a white
page. User bubbles right-aligned with a subtle teal tint; assistant bubbles
left-aligned on off-white. Pathway / plasmid / compare blocks render inline
as light-weight cards inside the assistant message.
"""
from __future__ import annotations

import gradio as gr

C = {
    "bg":          "#FFFFFF",
    "surface":     "#F7F7F8",
    "surface_alt": "#ECECEF",
    "text":        "#0F172A",
    "text_dim":    "#52525B",
    "text_faint":  "#8A8A93",
    "primary":     "#0F766E",
    "primary_hov": "#0D5C57",
    "primary_soft":"#E6F2F0",
    "accent":      "#B45309",
    "purple":      "#6D28D9",
    "border":      "#E5E7EB",
    "border_soft": "#EEF0F2",
    "link":        "#0369A1",
    "success":     "#166534",
    "warn":        "#92400E",
    "danger":      "#991B1B",
}


def make_theme() -> gr.themes.Base:
    return gr.themes.Base(
        primary_hue=gr.themes.Color(
            c50="#E6F2F0",  c100="#C3E0DB", c200="#9FCCC5",
            c300="#7AB9AF", c400="#4FA498", c500="#0F766E",
            c600="#0D5C57", c700="#0A4743", c800="#073230", c900="#031E1C",
            c950="#02100F",
        ),
        neutral_hue=gr.themes.Color(
            c50="#FFFFFF",  c100="#F7F7F8", c200="#ECECEF",
            c300="#D4D4D8", c400="#A1A1AA", c500="#71717A",
            c600="#52525B", c700="#3F3F46", c800="#27272A",
            c900="#0F172A", c950="#030712",
        ),
        font=[gr.themes.GoogleFont("Inter"), "system-ui", "-apple-system", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "monospace"],
    ).set(
        body_background_fill=C["bg"],
        body_text_color=C["text"],
        background_fill_primary=C["bg"],
        background_fill_secondary=C["surface"],
        block_background_fill=C["bg"],
        block_border_color=C["border"],
        block_border_width="0px",
        block_label_text_color=C["text_dim"],
        block_title_text_color=C["text"],
        button_primary_background_fill=C["primary"],
        button_primary_background_fill_hover=C["primary_hov"],
        button_primary_text_color="#FFFFFF",
        button_secondary_background_fill=C["surface"],
        button_secondary_text_color=C["text"],
        button_secondary_border_color=C["border"],
        border_color_accent=C["primary"],
        color_accent=C["primary"],
        color_accent_soft=C["primary_soft"],
        input_background_fill=C["bg"],
        input_border_color=C["border"],
        input_border_color_focus=C["primary"],
        code_background_fill=C["surface"],
    )


CUSTOM_CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ========== force light mode (kill Gradio dark auto-detect) ========== */
html, html.dark, body, body.dark {{
    color-scheme: light !important;
    background: {C['bg']} !important;
    color: {C['text']} !important;
}}
.dark {{ color-scheme: light !important; }}
.dark .gradio-container,
.dark .gradio-container *,
html.dark .gradio-container,
html.dark .gradio-container * {{
    background-color: unset;
    color: {C['text']} !important;
}}
.dark .gradio-container {{ background: {C['bg']} !important; }}
.dark .chat-thread,
.dark .chat-thread > div {{ background: {C['bg']} !important; }}
.dark .chat-thread [data-testid="bot"],
.dark .chat-thread .bot-row .message {{
    background: {C['surface']} !important;
    color: {C['text']} !important;
    border-color: {C['border']} !important;
}}
.dark .chat-thread [data-testid="user"],
.dark .chat-thread .user-row .message {{
    background: {C['primary_soft']} !important;
    color: {C['text']} !important;
}}
.dark .input-row {{ background: {C['bg']} !important; }}
.dark .input-row textarea {{ background: {C['bg']} !important; color: {C['text']} !important; }}

/* ========== page chrome ========== */
html, body, .gradio-container {{
    background: {C['bg']} !important;
    color: {C['text']} !important;
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
}}
.gradio-container {{
    max-width: 1040px !important;
    width: 100% !important;
    margin: 0 auto !important;
    padding: 0.8rem 1.2rem 1.1rem 1.2rem !important;
    min-height: 100vh !important;
}}
footer, .show-api, .api-link {{ display: none !important; }}

h1, h2, h3, h4 {{
    color: {C['text']} !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    letter-spacing: -0.015em;
}}
a {{ color: {C['link']}; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
code, pre {{ font-family: 'JetBrains Mono', ui-monospace, monospace !important; }}

/* ========== minimal header ========== */
.app-header {{
    text-align: center;
    padding: 0.3rem 0 0.85rem 0;
    border: none;
}}
.app-title {{
    font-size: 1.15rem;
    font-weight: 600;
    color: {C['text']};
    letter-spacing: -0.01em;
}}
.app-title .dot {{
    display: inline-block;
    width: 7px; height: 7px;
    border-radius: 50%;
    background: {C['primary']};
    margin-right: 0.55rem;
    vertical-align: middle;
    transform: translateY(-2px);
}}
.app-subtitle {{
    color: {C['text_faint']};
    font-size: 0.78rem;
    margin-top: 0.15rem;
    font-weight: 400;
}}

/* ========== chat thread ========== */
.chat-thread {{
    background: {C['bg']} !important;
    border: none !important;
    min-height: 66vh;
    max-height: 74vh;
    padding: 0 !important;
    box-shadow: none !important;
    scroll-behavior: smooth;
}}
.chat-thread > div {{ background: {C['bg']} !important; }}

.chat-thread .bubble-wrap,
.chat-thread .message,
.chat-thread .message-wrap,
.chat-thread .message-row,
.chat-thread [data-testid="user"],
.chat-thread [data-testid="bot"] {{
    background: transparent !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    font-size: 0.98rem !important;
    line-height: 1.65 !important;
    color: {C['text']} !important;
}}

/* aggressive color forcing — Gradio sometimes injects inline white text */
.chat-thread *:not(code):not(pre) {{ color: {C['text']}; }}
.chat-thread .bot-row .message *,
.chat-thread [data-testid="bot"] * {{ color: {C['text']} !important; }}

/* assistant bubble */
.chat-thread .bot-row .message,
.chat-thread [data-testid="bot"] {{
    background: {C['surface']} !important;
    color: {C['text']} !important;
    border: 1px solid {C['border']} !important;
    border-radius: 14px !important;
    padding: 0.82rem 1rem !important;
    max-width: 92% !important;
    box-shadow: none !important;
}}
/* user bubble */
.chat-thread .user-row .message,
.chat-thread [data-testid="user"] {{
    background: {C['primary_soft']} !important;
    color: {C['text']} !important;
    border: 1px solid {C['primary']}22 !important;
    border-radius: 14px !important;
    padding: 0.72rem 1rem !important;
    max-width: 86% !important;
    box-shadow: none !important;
}}

/* inline markdown styling */
.chat-thread code {{
    background: rgba(15, 118, 110, 0.08) !important;
    color: {C['primary']} !important;
    border: 1px solid {C['primary']}22;
    padding: 0.08rem 0.35rem;
    border-radius: 4px;
    font-size: 0.86em;
}}
.chat-thread pre code {{ background: {C['surface']} !important; border: 1px solid {C['border']}; }}
.chat-thread strong {{ color: {C['text']}; }}
.chat-thread em     {{ color: {C['purple']}; }}
.chat-thread table  {{
    border-collapse: collapse; width: 100%;
    font-size: 0.9rem; margin: 0.5rem 0;
}}
.chat-thread th {{
    background: {C['surface']};
    border-bottom: 1px solid {C['border']};
    padding: 0.4rem 0.65rem; text-align: left;
    font-weight: 600; color: {C['text_dim']};
    font-size: 0.78rem; text-transform: uppercase;
    letter-spacing: 0.04em;
}}
.chat-thread td {{
    border-bottom: 1px solid {C['border_soft']};
    padding: 0.4rem 0.65rem; vertical-align: top;
}}
.chat-thread h1, .chat-thread h2, .chat-thread h3 {{
    margin-top: 0.9rem;
    font-size: 1rem;
    font-weight: 600;
}}

/* ========== input bar ========== */
.input-row {{
    position: sticky !important;
    bottom: 0 !important;
    z-index: 20 !important;
    margin-top: 0.55rem !important;
    padding: 0.5rem 0.5rem 0.3rem 0.5rem !important;
    background: rgba(255,255,255,0.94) !important;
    backdrop-filter: blur(8px);
    border: 1px solid {C['border']} !important;
    border-radius: 14px !important;
    box-shadow: 0 10px 24px rgba(15,23,42,0.06);
}}
.input-row textarea {{
    background: {C['bg']} !important;
    color: {C['text']} !important;
    border: none !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    font-size: 1rem !important;
    line-height: 1.5 !important;
    padding: 0.65rem 0.55rem !important;
    resize: none !important;
    box-shadow: none !important;
}}
.input-row textarea::placeholder {{ color: {C['text_faint']} !important; }}
.input-row textarea:focus {{ outline: none !important; box-shadow: none !important; }}
.input-row button.primary {{
    background: {C['primary']} !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 10px !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    font-weight: 500 !important;
    padding: 0.5rem 1rem !important;
    min-width: 70px !important;
}}
.input-row button.primary:hover {{ background: {C['primary_hov']} !important; }}
.input-row button.secondary {{
    background: {C['bg']} !important;
    color: {C['text_faint']} !important;
    border: 1px solid {C['border']} !important;
    border-radius: 10px !important;
    padding: 0.5rem 0.9rem !important;
    font-weight: 500;
}}
.input-row button.secondary:hover {{ color: {C['text']} !important; border-color: {C['text_faint']} !important; }}

/* hide empty block containers */
.gradio-container .block {{ box-shadow: none !important; border: none !important; background: transparent !important; }}

/* ========== inline renderers ========== */

/* pathway reaction scheme — subtle card, not a dashboard widget */
.pathway-flowchart {{
    margin: 0.6rem 0;
    padding: 0.8rem 0.6rem 0.4rem 0.6rem;
    background: {C['bg']};
    border: 1px solid {C['border']};
    border-radius: 10px;
    text-align: center;
}}
.pathway-title {{ display: none; }}
.path-node {{
    display: inline-block;
    min-width: 280px;
    max-width: 520px;
    padding: 0.55rem 0.85rem;
    background: {C['bg']};
    border: 1px solid {C['border']};
    border-left: 3px solid {C['primary']};
    border-radius: 8px;
    margin: 0 auto;
    text-align: left;
    box-shadow: 0 1px 2px rgba(15,23,42,0.03);
}}
.path-step-num {{
    color: {C['text_faint']};
    font-size: 0.66rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 0.25rem;
    font-weight: 600;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
}}
.path-reaction {{ font-size: 0.98rem; color: {C['text']}; }}
.path-substrate {{ color: {C['text']}; font-weight: 500; }}
.path-arrow {{ color: {C['primary']}; font-weight: 700; margin: 0 0.35em; }}
.path-product {{ color: {C['primary']}; font-weight: 600; }}
.path-enzyme {{
    color: {C['text_dim']};
    font-size: 0.83rem;
    margin-top: 0.3rem;
}}
.path-enzyme em {{ color: {C['accent']}; font-style: italic; }}
.path-meta {{
    margin-top: 0.35rem;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.74rem;
    display: flex; gap: 0.4rem; flex-wrap: wrap;
}}
.path-ec, .path-rxn {{
    color: {C['accent']} !important;
    background: #FEF3C7;
    padding: 0.08rem 0.45rem;
    border-radius: 4px;
    border: 1px solid #FCD34D;
    font-weight: 500;
    text-decoration: none !important;
}}
.path-ec:hover, .path-rxn:hover {{ background: #FDE68A; }}
.path-arrow-down {{
    color: {C['primary']};
    font-size: 1.1rem;
    line-height: 1;
    margin: 0.25rem 0;
    opacity: 0.55;
}}

/* confidence banner */
.confidence-banner {{
    display: flex; align-items: center; gap: 0.85rem;
    margin: 0.2rem 0 0.6rem 0;
    padding: 0.5rem 0.85rem;
    border-radius: 10px;
    border: 1px solid {C['border']};
    background: {C['bg']};
}}
.confidence-banner .conf-label {{
    font-size: 0.68rem; letter-spacing: 0.14em;
    text-transform: uppercase; font-weight: 600;
    color: {C['text_dim']};
    font-family: 'JetBrains Mono', ui-monospace, monospace;
}}
.confidence-banner .conf-score {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 1.2rem; font-weight: 700;
}}
.confidence-banner .conf-just {{ color: {C['text_dim']}; flex: 1; font-size: 0.88rem; }}
.confidence-high .conf-score {{ color: {C['success']}; }}
.confidence-high {{ border-left: 3px solid {C['success']}; }}
.confidence-med  .conf-score {{ color: {C['warn']}; }}
.confidence-med  {{ border-left: 3px solid {C['warn']}; }}
.confidence-low  .conf-score {{ color: {C['danger']}; }}
.confidence-low  {{ border-left: 3px solid {C['danger']}; }}

/* plasmid map + compare table blocks — subtle inline cards */
.plasmid-map, .route-compare {{
    background: {C['bg']};
    border: 1px solid {C['border']};
    border-radius: 10px;
    padding: 0.8rem;
    margin: 0.6rem 0;
}}
.plasmid-map {{ text-align: center; }}
.plasmid-map svg {{ max-width: 100%; height: auto; }}
.route-compare table {{
    border-collapse: collapse; width: 100%; font-size: 0.88rem;
}}
.route-compare th {{
    background: {C['surface']};
    border-bottom: 1px solid {C['border']};
    padding: 0.5rem 0.7rem;
    text-align: left;
    font-weight: 600;
    color: {C['text_dim']};
    font-size: 0.76rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}
.route-compare td {{
    border-bottom: 1px solid {C['border_soft']};
    padding: 0.5rem 0.7rem;
    vertical-align: top;
}}
.route-compare .recommended {{
    background: {C['primary_soft']};
    border-left: 3px solid {C['primary']};
}}

/* citations "details" accordion — minimal */
details {{
    background: transparent;
    border-top: 1px solid {C['border_soft']};
    padding: 0.45rem 0 0 0;
    margin-top: 0.8rem;
}}
details summary {{
    color: {C['text_faint']};
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    list-style: none;
    padding: 0.2rem 0;
}}
details summary::-webkit-details-marker {{ display: none; }}
details[open] summary {{ color: {C['primary']}; }}
details table th {{
    color: {C['text_dim']} !important;
    font-size: 0.74rem !important;
    padding: 0.2rem 0.8rem 0.2rem 0 !important;
    background: transparent !important;
    border: none !important;
}}
details table td {{
    padding: 0.2rem 0 !important;
    border: none !important;
}}

/* ========== showcase preset chips ========== */
.showcase-row {{
    margin: 0.05rem 0 0.08rem 0 !important;
    padding: 0 !important;
    background: transparent !important;
    width: 100% !important;
}}
.showcase-label {{
    display: block;
    width: 100%;
    text-align: left;
    color: {C['text_faint']};
    font-size: 0.74rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    padding: 0.2rem 0.15rem;
    font-weight: 500;
}}
.showcase-chips {{
    margin: 0.08rem 0 0.42rem 0 !important;
    padding: 0 !important;
    gap: 0.5rem !important;
    background: transparent !important;
    width: 100% !important;
}}
.showcase-chip {{
    background: {C['surface']} !important;
    color: {C['text_dim']} !important;
    border: 1px solid {C['border']} !important;
    border-radius: 999px !important;
    padding: 0.38rem 0.82rem !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    font-size: 0.79rem !important;
    font-weight: 500 !important;
    letter-spacing: -0.005em !important;
    white-space: nowrap !important;
    cursor: pointer !important;
    transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease !important;
    box-shadow: none !important;
    min-height: 0 !important;
}}
.showcase-chip:hover {{
    background: {C['primary_soft']} !important;
    border-color: {C['primary']} !important;
    color: {C['primary']} !important;
}}
.showcase-chip:active {{ transform: translateY(1px); }}

/* reference card shown above agent output in showcase mode */
.reference-card {{
    background: #FFFBEB;
    border: 1px solid #FDE68A;
    border-radius: 10px;
    padding: 0;
    margin: 0.15rem 0 0.45rem 0;
    font-family: 'Inter', system-ui, sans-serif;
    color: {C['text']};
}}
.reference-card-summary {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.7rem;
    flex-wrap: wrap;
    padding: 0.65rem 0.85rem;
    cursor: pointer;
    list-style: none;
}}
.reference-card-summary::-webkit-details-marker {{ display: none; }}
.reference-card-body {{
    padding: 0 0.85rem 0.75rem 0.85rem;
}}
.reference-card-toggle {{
    color: {C['text_faint']};
    font-size: 0.72rem;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}}
.reference-card-tag {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.68rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: {C['accent']};
    font-weight: 600;
}}
.reference-card-title {{
    font-size: 1rem;
    font-weight: 600;
    color: {C['text']};
    letter-spacing: -0.01em;
}}
.reference-card-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.86rem;
    margin: 0;
}}
.reference-card-table th {{
    text-align: left;
    color: {C['text_dim']};
    font-weight: 600;
    font-size: 0.74rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 0.25rem 0.7rem 0.25rem 0;
    width: 110px;
    white-space: nowrap;
    vertical-align: top;
    background: transparent !important;
    border: none !important;
}}
.reference-card-table td {{
    color: {C['text']};
    padding: 0.25rem 0;
    vertical-align: top;
    border: none !important;
}}
.reference-card-hint {{
    margin-top: 0.45rem;
    font-size: 0.76rem;
    color: {C['text_dim']};
    font-style: italic;
}}

/* ========== compact live trace indicator (ChatGPT-style) ========== */
.trace {{
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    padding: 0.1rem 0;
}}
.trace-head {{
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.05rem 0;
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 0.88rem;
    color: {C['text_dim']};
}}
.trace-dots {{ display: inline-flex; gap: 0.22rem; align-items: center; }}
.trace-dot {{
    width: 5px; height: 5px;
    border-radius: 50%;
    background: {C['primary']};
    opacity: 0.3;
    animation: trace-pulse 1.2s infinite ease-in-out;
}}
.trace-dot:nth-child(2) {{ animation-delay: 0.2s; }}
.trace-dot:nth-child(3) {{ animation-delay: 0.4s; }}
.trace-status {{ font-style: italic; }}
.trace-status code {{
    background: rgba(15,118,110,0.08);
    padding: 0.08rem 0.35rem;
    border-radius: 4px;
    color: {C['primary']};
    font-size: 0.86em;
    font-style: normal;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
}}
@keyframes trace-pulse {{
    0%, 80%, 100% {{ opacity: 0.22; transform: scale(0.85); }}
    40% {{ opacity: 1; transform: scale(1); }}
}}

.trace-details {{
    margin: 0;
    padding: 0;
    border: none;
}}
.trace-details summary {{
    color: {C['text_faint']};
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.7rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    list-style: none;
    padding: 0.15rem 0.1rem;
}}
.trace-details summary::-webkit-details-marker {{ display: none; }}
.trace-details[open] summary {{ color: {C['primary']}; }}
.trace-details-body {{
    display: flex; flex-direction: column; gap: 0.3rem;
    margin-top: 0.4rem;
    padding: 0.4rem 0.55rem;
    background: {C['surface']};
    border: 1px solid {C['border_soft']};
    border-radius: 8px;
}}
.trace-row {{
    display: block;
    font-size: 0.82rem;
    color: {C['text']};
    padding: 0.2rem 0;
}}
.trace-row-tag {{
    display: inline-block;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.64rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: {C['text_faint']};
    margin-right: 0.45rem;
    font-weight: 600;
}}
.trace-row-thought .trace-row-tag {{ color: {C['primary']}; }}
.trace-row-tool    .trace-row-tag {{ color: {C['accent']}; }}
.trace-row-body code {{
    background: rgba(15,118,110,0.08);
    padding: 0.08rem 0.35rem;
    border-radius: 4px;
    color: {C['primary']};
    font-size: 0.86em;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
}}
.trace-dim {{ color: {C['text_dim']}; font-size: 0.85em; }}
.trace-row-obs {{
    margin: 0.25rem 0 0 2.1rem;
    padding: 0.3rem 0.5rem;
    background: {C['bg']};
    border: 1px solid {C['border_soft']};
    border-radius: 6px;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.74rem;
    color: {C['text_dim']};
    white-space: pre-wrap;
    word-break: break-word;
}}

/* ========== visible inline "Actions" block (default mode) ========== */
.actions-inline {{
    margin: 0.3rem 0 0.15rem 0;
    padding: 0.45rem 0.6rem;
    background: {C['surface']};
    border: 1px solid {C['border_soft']};
    border-radius: 8px;
}}
.actions-label {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.62rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: {C['text_faint']};
    font-weight: 600;
    margin-bottom: 0.35rem;
}}
.act-row {{
    display: flex;
    gap: 0.55rem;
    padding: 0.15rem 0;
    line-height: 1.45;
    align-items: baseline;
}}
.act-tag {{
    display: inline-block;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.6rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: {C['text_faint']};
    min-width: 3.3em;
    font-weight: 600;
}}
.act-tool .act-tag    {{ color: {C['accent']}; }}
.act-thought .act-tag {{ color: {C['primary']}; }}
.act-more .act-tag    {{ color: {C['text_faint']}; }}
.act-body {{
    color: {C['text']};
    flex: 1;
    font-size: 0.84rem;
    word-break: break-word;
}}
.act-body code {{
    background: rgba(15,118,110,0.08);
    padding: 0.05rem 0.32rem;
    border-radius: 4px;
    color: {C['primary']};
    font-size: 0.78rem;
    font-family: 'JetBrains Mono', ui-monospace, monospace;
}}

.assistant-live {{
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
}}
.stream-preview {{
    color: {C['text']};
    line-height: 1.68;
    font-size: 0.96rem;
    white-space: normal;
    word-break: break-word;
}}
.stream-caret {{
    color: {C['primary']};
    font-weight: 700;
    margin-left: 0.12rem;
    animation: trace-pulse 1s infinite ease-in-out;
}}
.act-args {{
    color: {C['text_dim']};
    font-size: 0.92em;
    margin-left: 0.15rem;
}}

/* collapsed reasoning-trace shown after the final answer */
.reasoning-trace {{
    margin-top: 0.8rem;
    border-top: 1px solid {C['border_soft']};
    padding-top: 0.5rem;
}}
.reasoning-trace summary {{
    color: {C['text_faint']};
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    list-style: none;
}}
.reasoning-trace summary::-webkit-details-marker {{ display: none; }}
.reasoning-trace[open] summary {{ color: {C['primary']}; }}
.reasoning-trace ol {{
    margin: 0.4rem 0 0 1.2rem;
    padding: 0;
    color: {C['text_dim']};
    font-size: 0.86rem;
}}
.reasoning-trace ol li {{ margin: 0.15rem 0; }}

/* ========== plan card (in-bubble) ========== */
.plan-wrap {{
    margin: 0.6rem 0 0 0;
    padding: 0.75rem 0.85rem;
    background: {C['primary_soft']};
    border: 1px solid {C['primary']}33;
    border-radius: 10px;
}}
.plan-header {{
    font-size: 0.78rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: {C['text_dim']};
    margin-bottom: 0.55rem;
}}
.plan-header strong {{ color: {C['text']}; font-weight: 700; }}
.plan-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.55rem;
}}
@media (max-width: 720px) {{
    .plan-grid {{ grid-template-columns: 1fr; }}
}}
.plan-card {{
    display: block;
    text-align: left;
    background: {C['bg']};
    border: 1px solid {C['border']};
    border-radius: 9px;
    padding: 0.6rem 0.75rem;
    cursor: default;
    font-family: 'Inter', system-ui, sans-serif;
    color: {C['text']};
}}
.plan-card-head {{ display: flex; align-items: baseline; gap: 0.5rem; margin-bottom: 0.3rem; }}
.plan-card-id {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.78rem;
    font-weight: 700;
    color: {C['primary']};
    padding: 0.05rem 0.35rem;
    background: rgba(15,118,110,0.1);
    border-radius: 4px;
}}
.plan-card-title {{ font-weight: 600; font-size: 0.92rem; }}
.plan-card-badges {{ display: flex; flex-wrap: wrap; gap: 0.3rem; margin-bottom: 0.35rem; }}
.plan-badge {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.65rem;
    letter-spacing: 0.05em;
    padding: 0.08rem 0.4rem;
    border-radius: 4px;
    background: {C['surface']};
    color: {C['text_dim']};
    border: 1px solid {C['border']};
}}
.plan-badge-microbial {{ background: #ECFDF5; color: #065F46; border-color: #A7F3D0; }}
.plan-badge-chemical  {{ background: #EFF6FF; color: #1E40AF; border-color: #BFDBFE; }}
.plan-badge-hybrid    {{ background: #FDF4FF; color: #86198F; border-color: #F5D0FE; }}
.plan-badge-host      {{ background: #FEF3C7; color: #92400E; border-color: #FCD34D; }}
.plan-card-summary {{
    color: {C['text_dim']};
    font-size: 0.85rem;
    line-height: 1.5;
    margin-bottom: 0.35rem;
}}
.plan-card-action {{
    font-size: 0.72rem;
    font-weight: 600;
    color: {C['primary']};
    letter-spacing: 0.02em;
}}
.plan-hint {{
    margin-top: 0.55rem;
    font-size: 0.76rem;
    color: {C['text_dim']};
    font-style: italic;
}}

/* ========== plan action buttons (below chat) ========== */
.plan-action-row {{
    margin: 0.25rem 0 0.45rem 0 !important;
    padding: 0 !important;
    gap: 0.45rem !important;
    background: transparent !important;
}}
.plan-action-btn {{
    background: {C['primary']} !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 999px !important;
    padding: 0.4rem 0.9rem !important;
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    box-shadow: 0 1px 3px rgba(15,118,110,0.25) !important;
    min-height: 0 !important;
    white-space: nowrap !important;
}}
.plan-action-btn:hover {{
    background: {C['primary_hov']} !important;
    color: #FFFFFF !important;
}}

/* scrollbars */
.chat-thread::-webkit-scrollbar {{ width: 8px; }}
.chat-thread::-webkit-scrollbar-track {{ background: {C['bg']}; }}
.chat-thread::-webkit-scrollbar-thumb {{ background: {C['border']}; border-radius: 4px; }}
.chat-thread::-webkit-scrollbar-thumb:hover {{ background: {C['text_faint']}; }}

/* ============================================================
   Legacy workspace shell styles retained for non-default modes
   ============================================================ */

/* header — add a right-aligned status pill */
.app-header {{ position: relative; }}
.app-header-meta {{
    display: flex;
    justify-content: center;
    margin-top: 0.35rem;
}}
.app-header-pill {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.64rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: {C['text_dim']};
    background: {C['surface']};
    border: 1px solid {C['border']};
    border-radius: 999px;
    padding: 0.15rem 0.65rem;
}}

/* workspace grid row */
.workspace-row {{
    align-items: stretch !important;
    gap: 1rem !important;
    margin-bottom: 0.2rem !important;
}}
.workspace-row > .gr-column {{
    min-width: 0 !important;
}}
.workspace-row > .workspace-rail {{
    flex: 2 1 18rem !important;
    max-width: 20rem !important;
}}
.workspace-row > .workspace-center {{
    flex: 6 1 0 !important;
}}
.workspace-row > .evidence-rail {{
    flex: 2 1 19rem !important;
    max-width: 22rem !important;
}}

/* left rail */
.workspace-rail {{
    background: {C['bg']} !important;
    border: 1px solid {C['border']} !important;
    border-radius: 12px !important;
    padding: 0.85rem 0.75rem !important;
    min-width: 16rem !important;
    align-self: stretch;
    overflow: hidden;
}}
.ws-rail {{
    display: flex;
    flex-direction: column;
    gap: 1rem;
    font-family: 'Inter', system-ui, sans-serif;
}}
.ws-section {{
    min-width: 0;
}}
.ws-section-head {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.64rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: {C['text_faint']};
    font-weight: 600;
    margin-bottom: 0.35rem;
}}
.ws-placeholder {{
    color: {C['text_dim']};
    font-size: 0.82rem;
    line-height: 1.45;
    padding: 0.4rem 0.55rem;
    background: {C['surface']};
    border: 1px dashed {C['border']};
    border-radius: 8px;
    white-space: normal;
    overflow-wrap: break-word;
    word-break: normal;
}}
.ws-status {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: {C['text_dim']};
    font-size: 0.82rem;
    min-width: 0;
}}
.ws-status-sub {{ margin-top: 0.35rem; }}
.ws-status-dim {{ color: {C['text_faint']}; font-size: 0.78rem; }}
.ws-status-dot {{
    width: 7px; height: 7px;
    border-radius: 50%;
    background: {C['success']};
    box-shadow: 0 0 0 2px rgba(22,101,52,0.15);
    flex-shrink: 0;
}}
.ws-status-text {{
    color: {C['text']};
    font-weight: 500;
    white-space: normal;
    overflow-wrap: break-word;
}}

/* center column — just carries the existing chat stack */
.workspace-center {{
    min-width: 0 !important;
}}
.workspace-center > .gr-row {{
    width: 100% !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
}}
.chat-thread {{
    width: 100% !important;
}}
.input-row {{
    align-items: end !important;
}}

/* right evidence rail */
.evidence-rail {{
    background: {C['bg']} !important;
    border: 1px solid {C['border']} !important;
    border-radius: 12px !important;
    padding: 0.85rem 0.75rem !important;
    min-width: 18rem !important;
    align-self: stretch;
    overflow: hidden;
}}
.evidence-panel {{
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
    font-family: 'Inter', system-ui, sans-serif;
    min-width: 0;
}}
.ev-header {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.68rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: {C['text']};
    font-weight: 700;
    padding-bottom: 0.3rem;
    border-bottom: 1px solid {C['border_soft']};
}}
.ev-empty {{
    color: {C['text_dim']};
    font-size: 0.82rem;
    line-height: 1.5;
    padding: 0.6rem 0.55rem;
    background: {C['surface']};
    border: 1px dashed {C['border']};
    border-radius: 8px;
    white-space: normal;
    overflow-wrap: break-word;
    word-break: normal;
}}
.ev-footer {{
    color: {C['text_faint']};
    font-size: 0.72rem;
    font-style: italic;
    line-height: 1.45;
    padding-top: 0.3rem;
    border-top: 1px solid {C['border_soft']};
    white-space: normal;
    overflow-wrap: break-word;
}}
.ev-section {{
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
}}
.ev-section-head {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.62rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: {C['text_faint']};
    font-weight: 600;
}}
.ev-stat {{
    font-size: 0.88rem;
    color: {C['text']};
    font-weight: 500;
}}
.ev-hint {{
    font-size: 0.74rem;
    color: {C['text_faint']};
    font-style: italic;
    white-space: normal;
    overflow-wrap: break-word;
}}
.ev-conf-score {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 1.35rem;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.01em;
}}
.ev-conf-high {{ color: {C['success']}; }}
.ev-conf-med  {{ color: {C['warn']}; }}
.ev-conf-low  {{ color: {C['danger']}; }}
.ev-conf-just {{
    color: {C['text_dim']};
    font-size: 0.82rem;
    line-height: 1.4;
    white-space: normal;
    overflow-wrap: break-word;
}}
.ev-cite-row {{
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.35rem 0.4rem;
    margin-bottom: 0.25rem;
}}
.ev-cite-label {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.62rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: {C['text_faint']};
    font-weight: 600;
    min-width: 4.2rem;
    white-space: normal;
    overflow-wrap: break-word;
}}
.ev-chip {{
    display: inline-block;
    padding: 0.08rem 0.45rem;
    background: rgba(15,118,110,0.08);
    border: 1px solid {C['primary']}22;
    border-radius: 4px;
    text-decoration: none !important;
    font-size: 0.78rem;
    white-space: nowrap;
    flex: 0 0 auto;
}}
.ev-chip:hover {{ background: {C['primary_soft']}; border-color: {C['primary']}; }}
.ev-chip code {{
    background: transparent !important;
    color: {C['primary']} !important;
    border: none !important;
    padding: 0 !important;
    font-size: 0.78rem;
}}
/* citation-verification state badges (Phase 9) */
.ev-chip-verified {{
    background: rgba(16,185,129,0.10);
    border-color: #10b98155;
}}
.ev-chip-verified code {{ color: #047857 !important; }}
.ev-chip-unresolved {{
    background: rgba(220,38,38,0.08);
    border-color: #dc262644;
}}
.ev-chip-unresolved code {{ color: #b91c1c !important; }}
.ev-chip-inferred {{
    background: rgba(148,163,184,0.10);
    border-color: #94a3b844;
}}
.ev-chip-inferred code {{ color: #475569 !important; }}
.ev-chip-status {{
    font-size: 0.62rem;
    margin-left: 0.25rem;
    padding: 0 0.28rem;
    border-radius: 3px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    opacity: 0.85;
    vertical-align: baseline;
}}
.ev-chip-verified .ev-chip-status {{ color: #047857; }}
.ev-chip-unresolved .ev-chip-status {{ color: #b91c1c; }}
.ev-chip-inferred  .ev-chip-status {{ color: #475569; }}
.ev-verify-summary {{
    font-size: 0.72rem;
    color: {C['text_dim']};
    margin: 0.1rem 0 0.45rem 0;
    display: flex;
    gap: 0.55rem;
    flex-wrap: wrap;
}}
.ev-verify-summary span {{ display: inline-flex; align-items: center; gap: 0.25rem; }}
.ev-verify-dot {{
    width: 0.55rem; height: 0.55rem; border-radius: 50%;
    display: inline-block;
}}
.ev-verify-dot-verified   {{ background: #10b981; }}
.ev-verify-dot-unresolved {{ background: #dc2626; }}
.ev-verify-dot-inferred   {{ background: #94a3b8; }}

/* bottom workflow strip */
.workflow-strip-label-row {{
    margin: 1.15rem 0 0.2rem 0 !important;
    padding: 0 !important;
    background: transparent !important;
    border-top: 1px solid {C['border_soft']};
    padding-top: 0.9rem !important;
}}
.workflow-strip-label {{
    font-family: 'JetBrains Mono', ui-monospace, monospace;
    font-size: 0.68rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: {C['text_faint']};
    padding: 0.1rem 0.2rem;
}}
.workflow-strip {{
    gap: 0.45rem !important;
    flex-wrap: wrap !important;
    padding: 0.1rem 0.2rem 0.2rem 0.2rem !important;
    margin-bottom: 0.2rem !important;
    background: transparent !important;
}}
.workflow-btn {{
    background: {C['bg']} !important;
    color: {C['text_faint']} !important;
    border: 1px dashed {C['border']} !important;
    border-radius: 8px !important;
    padding: 0.5rem 0.85rem !important;
    font-family: 'Inter', system-ui, sans-serif !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    box-shadow: none !important;
    cursor: not-allowed !important;
    opacity: 0.75;
    min-height: 0 !important;
    white-space: nowrap !important;
}}
.workflow-btn:hover {{
    background: {C['surface']} !important;
    color: {C['text_dim']} !important;
    border-color: {C['text_faint']} !important;
}}
/* Gradio overlays its own disabled styling — keep our dashed look */
.workflow-btn:disabled, .workflow-btn[disabled] {{
    background: {C['bg']} !important;
    color: {C['text_faint']} !important;
    border: 1px dashed {C['border']} !important;
    opacity: 0.75 !important;
}}

/* ========== responsive: stack rails below chat on narrow viewports ========== */
@media (max-width: 1080px) {{
    .workspace-row {{
        flex-direction: column !important;
        gap: 0.6rem !important;
    }}
    .workspace-rail, .evidence-rail {{
        width: 100% !important;
        min-width: 0 !important;
    }}
    /* keep the center chat first on mobile for task-focus */
    .workspace-center {{ order: 1 !important; }}
    .evidence-rail    {{ order: 2 !important; }}
    .workspace-rail   {{ order: 3 !important; }}
    .ws-rail {{
        flex-direction: row;
        flex-wrap: wrap;
        gap: 0.7rem;
    }}
    .ws-section {{ flex: 1 1 220px; }}
}}
@media (max-width: 640px) {{
    .gradio-container {{ padding: 0.65rem 0.8rem 1rem 0.8rem !important; }}
    .chat-thread {{ min-height: 58vh; max-height: 70vh; }}
    .workflow-strip {{ gap: 0.35rem !important; }}
    .workflow-btn {{ font-size: 0.74rem !important; padding: 0.4rem 0.65rem !important; }}
}}
"""

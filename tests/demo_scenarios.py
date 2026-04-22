"""
MetaboAgent — Demo Scenarios
Three showcase molecules for hackathon demo.
Run: python tests/demo_scenarios.py
"""

SCENARIOS = [
    {
        "id": "artemisinic_acid",
        "query": "Design a microbial strain to produce artemisinic acid for antimalarial drug synthesis",
        "target": {
            "name": "Artemisinic acid",
            "kegg_id": "C20309",
            "class": "Sesquiterpene (C15)",
            "application": "Antimalarial medicine — precursor to artemisinin (WHO essential medicine)",
        },
        "expected": {
            "host": "Saccharomyces cerevisiae",
            "host_rationale": "Native MVA pathway provides FPP at high flux; prior success (Keasling lab)",
            "key_pathway": "Acetyl-CoA → MVA → IPP/DMAPP → FPP → Amorphadiene → Artemisinic alcohol → Artemisinic aldehyde → Artemisinic acid",
            "key_enzymes": [
                {"gene": "ADS", "name": "Amorphadiene synthase", "source": "Artemisia annua", "ec": "4.2.3.24"},
                {"gene": "CYP71AV1", "name": "Amorphadiene oxidase (P450)", "source": "Artemisia annua", "ec": "1.14.14.51"},
                {"gene": "ADH1", "name": "Artemisinic alcohol dehydrogenase", "source": "Artemisia annua"},
                {"gene": "ALDH1", "name": "Artemisinic aldehyde dehydrogenase", "source": "Artemisia annua"},
            ],
            "overexpress": ["tHMG1 (truncated HMG-CoA reductase)", "ERG20 (FPP synthase)", "upc2-1 (sterol pathway regulator)"],
            "knockout": ["ERG9 (squalene synthase — reduce FPP diversion to sterols)"],
            "key_references": [
                "Ro et al. (2006) Nature 440:940 — first artemisinic acid production in yeast",
                "Paddon et al. (2013) Nature 496:528 — industrial-scale production at 25g/L",
            ],
        },
    },
    {
        "id": "taxadiene",
        "query": "Design a strain to produce taxadiene as a precursor to the anticancer drug Taxol (paclitaxel)",
        "target": {
            "name": "Taxadiene",
            "kegg_id": "C11894",
            "class": "Diterpene (C20)",
            "application": "Anticancer — precursor to Taxol/paclitaxel (breast, ovarian, lung cancer)",
        },
        "expected": {
            "host": "Escherichia coli",
            "host_rationale": "Engineered MEP pathway can supply GGPP; faster growth for optimization",
            "key_pathway": "Pyruvate + G3P → MEP pathway → IPP/DMAPP → GPP → FPP → GGPP → Taxadiene",
            "key_enzymes": [
                {"gene": "TASY/txs", "name": "Taxadiene synthase", "source": "Taxus brevifolia", "ec": "4.2.3.17"},
                {"gene": "GGPPS", "name": "GGPP synthase", "source": "Taxus canadensis", "ec": "2.5.1.29"},
            ],
            "overexpress": ["dxs (1-deoxy-D-xylulose-5-phosphate synthase)", "idi (IPP isomerase)", "ispD, ispF (MEP pathway)"],
            "knockout": [],
            "key_references": [
                "Ajikumar et al. (2010) Science 330:70 — 1g/L taxadiene in E. coli via multivariate modular pathway engineering",
                "Huang et al. (2001) Biotechnol Bioeng — taxadiene synthase characterization",
            ],
        },
    },
    {
        "id": "vanillin",
        "query": "Design a strain to produce vanillin from glucose as a sustainable green chemistry alternative",
        "target": {
            "name": "Vanillin",
            "kegg_id": "C00755",
            "class": "Phenylpropanoid / aromatic aldehyde",
            "application": "Green chemistry — sustainable flavor/fragrance, replacing petroleum synthesis",
        },
        "expected": {
            "host": "Escherichia coli or Saccharomyces cerevisiae",
            "host_rationale": "Native shikimate pathway provides 3-dehydroshikimate precursor",
            "key_pathway": "Glucose → PEP + E4P → Shikimate pathway → 3-Dehydroshikimate → Protocatechuic acid → Vanillic acid → Vanillin",
            "key_enzymes": [
                {"gene": "3DSD/aroZ", "name": "3-dehydroshikimate dehydratase", "source": "Podospora anserina", "ec": "4.2.1.118"},
                {"gene": "ACAR", "name": "Aryl carboxylic acid reductase", "source": "Nocardia iowensis", "ec": "1.2.1.30"},
                {"gene": "OMT/COMT", "name": "Catechol-O-methyltransferase", "source": "Homo sapiens", "ec": "2.1.1.6"},
            ],
            "overexpress": ["aroG (DAHP synthase, fbr mutant)", "aroB (DHQ synthase)", "aroD (DHQ dehydratase)"],
            "knockout": ["aroE (shikimate dehydrogenase — block shikimate branch)"],
            "key_references": [
                "Hansen et al. (2009) Appl Environ Microbiol — de novo vanillin biosynthesis in yeast",
                "Kunjapur et al. (2014) JACS — vanillin production in E. coli",
            ],
        },
    },
]


def print_scenario(scenario: dict):
    """Pretty-print a demo scenario."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    console.print(Panel(
        f"[bold]{scenario['target']['name']}[/bold]\n"
        f"[dim]{scenario['target']['application']}[/dim]\n\n"
        f"[cyan]Query:[/cyan] {scenario['query']}",
        title=f"Demo: {scenario['id']}",
        border_style="green",
    ))

    expected = scenario["expected"]

    table = Table(title="Expected Pathway Enzymes", show_header=True)
    table.add_column("Gene", style="bold")
    table.add_column("Name")
    table.add_column("Source")
    table.add_column("EC")
    for enz in expected["key_enzymes"]:
        table.add_row(
            enz.get("gene", ""),
            enz.get("name", ""),
            enz.get("source", ""),
            enz.get("ec", "—"),
        )
    console.print(table)

    console.print(f"\n[bold]Expected host:[/bold] {expected['host']}")
    console.print(f"[bold]Rationale:[/bold] {expected['host_rationale']}")
    console.print(f"[bold]Pathway:[/bold] {expected['key_pathway']}")
    console.print()


def run_live(scenario: dict, agent=None) -> dict:
    """Run the agent on a scenario and check the answer mentions expected enzymes/host."""
    import re as _re
    from agent.metabo_agent import build_agent, run

    agent = agent or build_agent()
    print(f"\n=== RUNNING: {scenario['id']} ===")
    result = run(agent, scenario["query"])
    answer = (result.get("answer") or "").lower()
    expected = scenario["expected"]

    # Check host mention
    host_match = any(h.lower() in answer for h in expected["host"].replace(" or ", ",").split(","))
    # Check any expected gene/enzyme name
    gene_hits = [e["gene"] for e in expected["key_enzymes"] if e["gene"].lower() in answer]
    # Check any EC number
    ec_hits = [e["ec"] for e in expected["key_enzymes"] if e.get("ec") and e["ec"] in answer]
    has_kegg_id = bool(_re.search(r"\bR\d{5}\b", result.get("answer") or ""))

    ok = host_match and (bool(gene_hits) or bool(ec_hits))
    print(f"  steps={len(result['steps'])}  host_match={host_match}  genes={gene_hits}  ECs={ec_hits}  has_kegg_id={has_kegg_id}")
    print("  --- answer snippet ---")
    print("  " + (result.get("answer") or "")[:500].replace("\n", "\n  "))
    return {"id": scenario["id"], "ok": ok, "steps": len(result["steps"]),
            "host_match": host_match, "gene_hits": gene_hits, "ec_hits": ec_hits}


def run_all_live():
    import sys
    from agent.metabo_agent import build_agent
    agent = build_agent()
    results = [run_live(s, agent) for s in SCENARIOS]
    print("\n=== DEMO RESULTS ===")
    for r in results:
        flag = "PASS" if r["ok"] else "FAIL"
        print(f"  [{flag}] {r['id']:20s}  host={r['host_match']}  genes={r['gene_hits']}  ECs={r['ec_hits']}")
    if not all(r["ok"] for r in results):
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Invoke the agent for each scenario.")
    args = parser.parse_args()
    if args.live:
        run_all_live()
    else:
        for s in SCENARIOS:
            print_scenario(s)

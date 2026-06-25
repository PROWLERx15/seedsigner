"""
Generates Graphviz DOT and SVG diagrams per module from the raw DOT output.
Groups views into modules and renders them with full transition details.

Usage:
    python3 generate_dot_graph.py
"""

import re
import sys
import subprocess
import textwrap
from pathlib import Path

SRC = "outputs/dot_graph.txt"
edge_re = re.compile(r'^\s*"([^"]+)"\s*->\s*"([^"]+)"\s*\[label="(.*)"\];\s*$')

# Setup Output Directories
DOT_DIR = Path("graphs/dot")
SVG_DIR = Path("graphs/svg")
DOT_DIR.mkdir(parents=True, exist_ok=True)
SVG_DIR.mkdir(parents=True, exist_ok=True)

edges = []
with open(SRC) as f:
    for line in f:
        m = edge_re.match(line)
        if m:
            edges.append(m.groups()) 

seen = set()
edges = [e for e in edges if not (e in seen or seen.add(e))]

CLUSTER_RULES = [
    ("Scan", lambda n: n.startswith("Scan")),
    ("PSBT", lambda n: n.startswith("PSBT")),
    ("Seed", lambda n: n.startswith("Seed")),
    ("Settings", lambda n: n.startswith("Settings") or n == "LocaleSelectionView"),
    ("Tools", lambda n: n.startswith("Tools")),
    ("Address", lambda n: n.startswith("Address")),
    ("Power", lambda n: n.startswith("Power") or n == "RestartView"),
    (
        "System",
        lambda n: (
            n
            in {
                "MainMenuView",
                "[BACK]",
                "ErrorView",
                "NotYetImplementedView",
                "UnhandledExceptionView",
                "CameraConnectionErrorView",
                "OptionDisabledView",
                "RemoveMicroSDWarningView",
                "NetworkMismatchErrorView",
                "IOTestView",
                "DonateView",
                "blocking_view",
                "unblocking_view",
            }
        ),
    ),
]

def classify(node: str) -> str:
    for cname, rule in CLUSTER_RULES:
        if rule(node):
            return cname
    return "Other"

CLUSTER_COLORS = {
    "Scan": ("#E3F2FD", "#1E88E5"),
    "PSBT": ("#FFF3E0", "#FB8C00"),
    "Seed": ("#E8F5E9", "#43A047"),
    "Settings": ("#F3E5F5", "#8E24AA"),
    "Tools": ("#E0F7FA", "#00ACC1"),
    "Address": ("#FCE4EC", "#D81B60"),
    "Power": ("#ECEFF1", "#546E7A"),
    "System": ("#FFFDE7", "#F9A825"),
    "Other": ("#FAFAFA", "#757575"),
}

def wrap_condition(cond: str, width: int = 46) -> str:
    """Wraps condition strings for readability in DOT output."""
    if not cond:
        return ""
    cleaned = (
        cond.replace("self.", "")
        .replace("SettingsConstants.", "")
        .replace(" AND ", "  AND  ")
    )
    wrapped_lines = textwrap.wrap(cleaned, width=width, break_long_words=False)
    return "\\n".join(wrapped_lines)

def esc(s: str) -> str:
    return s.replace('"', '\\"')

def build_module_dot(module: str) -> str:
    intra = [] 
    boundary = []
    nodes = set()

    for s, d, c in edges:
        cs, cd = classify(s), classify(d)
        if cs == module and cd == module:
            intra.append((s, d, c))
            nodes.update([s, d])
        elif cs == module or cd == module:
            boundary.append((s, d, c))
            nodes.update([s, d])

    if not intra and not boundary:
        return ""

    module_nodes = {n for n in nodes if classify(n) == module}
    ext_nodes = nodes - module_nodes
    fill, border = CLUSTER_COLORS.get(module, CLUSTER_COLORS["Other"])

    out = []
    out.append(f"digraph {module}Module {{")
    out.append("    rankdir=TB;")
    out.append("    splines=spline;")
    out.append("    nodesep=0.55;")
    out.append("    ranksep=0.95;")
    out.append('    bgcolor="white";')
    out.append('    fontname="Helvetica";')
    out.append('    labelloc="t"; fontsize=20;')
    out.append(
        f'    label="{module}";'
    )
    out.append(
        f'    node [shape=box, style="rounded,filled", fontname="Helvetica",'
        f' fontsize=11, margin="0.18,0.10", color="{border}", fillcolor="{fill}"];'
    )
    out.append(
        '    edge [fontname="Helvetica", fontsize=8.5, color="#78909C",'
        " arrowsize=0.7, labeldistance=1.2];"
    )
    out.append("")

    out.append("    // External boundary nodes")
    for n in sorted(ext_nodes):
        ecolor = CLUSTER_COLORS.get(classify(n), CLUSTER_COLORS["Other"])[1]
        out.append(
            f'    "{n}" [style="rounded,filled,dashed", fillcolor="#FAFAFA",'
            f' color="{ecolor}", fontcolor="{ecolor}"];'
        )
    out.append("")

    out.append("    // Internal transitions")
    for s, d, c in intra:
        label = wrap_condition(c)
        attrs = []
        if label:
            attrs.append(f'label="{label}"')
        if s == d:
            attrs.append("style=dashed")
            attrs.append('color="#B0BEC5"')
        out.append(f'    "{s}" -> "{d}" [{", ".join(attrs)}];')
    out.append("")

    out.append("    // Boundary transitions")
    for s, d, c in boundary:
        label = wrap_condition(c)
        attrs = ["style=dashed", 'color="#B0BEC5"']
        if label:
            attrs.append(f'label="{label}"')
        out.append(f'    "{s}" -> "{d}" [{", ".join(attrs)}];')

    out.append("}")
    return "\n".join(out)

def main():
    ALL_MODULES = [
        "Scan",
        "PSBT",
        "Seed",
        "Settings",
        "Tools",
        "Address",
        "Power",
        "System",
    ]
    targets = sys.argv[1:] or ALL_MODULES

    for module in targets:
        dot_src = build_module_dot(module)
        if not dot_src:
            print(f"[skip] {module}: no edges")
            continue

        dot_path = DOT_DIR / f"{module.lower()}.dot"
        svg_path = SVG_DIR / f"{module.lower()}.svg"
        
        with open(dot_path, "w") as f:
            f.write(dot_src)

        try:
            result = subprocess.run(
                ["dot", "-Tsvg", str(dot_path), "-o", str(svg_path)],
                capture_output=True,
                text=True,
            )
            n_edges = dot_src.count(" -> ")
            status = "ok" if result.returncode == 0 else f"ERROR: {result.stderr.strip()[:200]}"
            print(f"[{status}] {module}: {n_edges} edges -> {svg_path}")
        except FileNotFoundError:
            print(f"[warning] {module}: Graphviz 'dot' not installed. Saved to {dot_path}, skipped SVG generation.")

if __name__ == "__main__":
    main()

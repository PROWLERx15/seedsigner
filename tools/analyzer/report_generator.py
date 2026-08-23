import json
import os
from dataclasses import asdict

from .models import Edge, ExtractedView


class JSONReport:
    def generate_json_report(
        self, views: list[ExtractedView], edges: list[Edge], coverage: dict = None
    ) -> str:
        output_path: str = "tools/analyzer/reports/analyzer_report.json"

        json_report = {
            "analyzer version": "1.0",
            "summary": {"total_views": len(views), "total_edges": len(edges)},
            "nodes": [asdict(view) for view in views],
            "edges": [asdict(edge) for edge in edges],
            "transitions": [],
            "coverage": coverage,
        }

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(json_report, f, sort_keys=True, indent=2)
            f.write("\n")

        return output_path


class TextReport:
    def generate_text_report(
        self, views: list[ExtractedView], edges: list[Edge], coverage: dict = None
    ) -> str:
        output_path: str = "tools/analyzer/reports/analyzer_report.txt"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        lines = []
        box_width = 57

        lines.append(f"╭{'─' * box_width}╮")
        lines.append(f"│{'SeedSigner Analyzer - Text Report'.center(box_width)}│")
        lines.append(f"╰{'─' * box_width}╯")
        lines.append("")
        lines.append(f"Total Views found: {len(views)}")
        lines.append(f"Total Edges found: {len(edges)}")
        lines.append("")

        views_by_module = {}
        for view in views:
            views_by_module.setdefault(view.defining_module, []).append(view)

        lines.append("=== NODES ===")
        for module, module_views in views_by_module.items():
            lines.append(f"\n▶ {module.split('/')[-1]} ({len(module_views)} views)")
            for view in module_views:
                base_classes = (
                    ", ".join(view.base_class_names)
                    if view.base_class_names
                    else "None"
                )
                lines.append(f"  · {view.view_class_name:<40} inherits: {base_classes}")
        lines.append("")

        edges_by_module = {}
        for edge in edges:
            edges_by_module.setdefault(edge.source_file, []).append(edge)

        lines.append("=== EDGES ===")
        for module, module_edges in edges_by_module.items():
            lines.append(f"\n▶ {module.split('/')[-1]} ({len(module_edges)} edges)")
            edges_by_source = {}
            for edge in module_edges:
                edges_by_source.setdefault(edge.source_view, []).append(edge)

            for source_view, source_edges in edges_by_source.items():
                lines.append(f"\n  {source_view} [SOURCE VIEW]")
                lines.append("  │")
                for i, edge in enumerate(source_edges):
                    is_last = i == len(source_edges) - 1
                    prefix = "└──▶" if is_last else "├──▶"
                    short_target = edge.target_view.split(".")[-1]
                    lines.append(
                        f"  {prefix} {short_target} [TARGET VIEW] (Line {edge.line_number})"
                    )
                    indent = "    " if is_last else "│   "
                    if edge.condition:
                        lines.append(f"  {indent} Conditions:")
                        for cond in edge.condition.split(" AND "):
                            lines.append(f"  {indent}   · {cond}")
                    if not is_last:
                        lines.append("  │")
        lines.append("")

        lines.append("=== COVERAGE ===")
        if coverage:
            lines.append(f"Total Edges:    {coverage['total_edges_count']}")
            lines.append(f"Tested Edges:   {coverage['tested_edges_count']}")
            lines.append(f"Coverage:       {coverage['percentage']}%")
            lines.append(f"Untested Edges: {len(coverage['untested_edges'])}")

            if coverage["untested_edges"]:
                lines.append("\n  [UNTESTED EDGES]")

                untested_by_src = {}
                for src, tgt in coverage["untested_edges"]:
                    untested_by_src.setdefault(src, []).append(tgt)

                for src, tgts in sorted(untested_by_src.items()):
                    lines.append(f"  · {src}")
                    for tgt in sorted(tgts):
                        lines.append(f"      └──▶ {tgt}")

            if coverage["unresolved_pairs"]:
                lines.append(
                    f"\n  [UNRESOLVED TEST PAIRS] ({coverage['unresolved_pairs_count']})"
                )

                unresolved_by_src = {}
                for src, tgt in coverage["unresolved_pairs"]:
                    unresolved_by_src.setdefault(src, []).append(tgt)

                for src, tgts in sorted(unresolved_by_src.items()):
                    lines.append(f"  · {src}")
                    for tgt in sorted(tgts):
                        lines.append(f"      └──▶ {tgt}")
        else:
            lines.append("coverage not computed in this run")
        lines.append("")

        with open(output_path, "w") as f:
            f.write("\n".join(lines))

        return output_path

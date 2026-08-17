"""
Phase 2: FlowTest Coverage Reconciliation Engine

Parses test_flows_*.py to extract tested navigation edges,
reconciles them against the static graph from navigation_graph.py,
and generates a coverage report with irregularity analysis.

Usage:
    python flow_test_extractor.py --coverage
    python flow_test_extractor.py --uncovered
    python flow_test_extractor.py --json > outputs/coverage_report.json
"""

import ast
import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

from navigation_graph import extract_edges, extract_view_inheritance, Edge

ROOT_DIR = Path(__file__).parents[2].resolve()
TESTS_DIR = ROOT_DIR / "tests"


# =============================================================================
# FlowTest Edge Extraction
# =============================================================================

class TestImportResolver(ast.NodeVisitor):
    """Resolves imports in test files to map short names to View class names."""

    def __init__(self):
        self.import_map: dict[str, str] = {}
        self.module_aliases: dict[str, str] = {}

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            for alias in node.names:
                local_name = alias.asname or alias.name
                self.import_map[local_name] = alias.name
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            local_name = alias.asname or alias.name
            self.module_aliases[local_name] = alias.name
        self.generic_visit(node)


class FlowTestExtractor(ast.NodeVisitor):
    """
    Extracts tested navigation edges from FlowTest sequences.

    Walks test_flows_*.py files sequentially. Every time a FlowStep is
    instantiated, it records an edge from the previous FlowStep. It also
    handles loops by adding self-edges, and resets the sequence whenever
    run_sequence is called.
    """

    def __init__(self, import_map: dict[str, str]):
        self.import_map = import_map
        self.tested_edges: list[tuple[str, str, str]] = []  # (source, target, test_name)
        self._current_test: str = ""
        self._current_file: str = ""
        self.last_view = None
        self.last_step_is_back = False
        self.in_loop = False

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if node.name.startswith("test_"):
            self._current_test = node.name
            self.last_view = None
            self.last_step_is_back = False
            self.in_loop = False
        self.generic_visit(node)

    def visit_For(self, node: ast.For):
        old_loop = self.in_loop
        self.in_loop = True
        self.generic_visit(node)
        self.in_loop = old_loop

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "run_sequence":
            self.generic_visit(node)
            self.last_view = None
            return

        if isinstance(node.func, ast.Name) and node.func.id == "FlowStep":
            if node.args:
                first = node.args[0]
                view_name = None
                if isinstance(first, ast.Name):
                    view_name = self.import_map.get(first.id, first.id)
                elif isinstance(first, ast.Attribute):
                    view_name = first.attr
                    
                if view_name:
                    if self.last_view:
                        self.tested_edges.append((
                            self.last_view,
                            view_name,
                            f"{self._current_file}::{self._current_test}",
                            self.last_step_is_back,
                        ))
                    self.last_view = view_name
                    self.last_step_is_back = self._step_is_back(node)
                    if self.in_loop:
                        self.tested_edges.append((
                            view_name,
                            view_name,
                            f"{self._current_file}::{self._current_test}",
                            False,
                        ))
        self.generic_visit(node)

    @staticmethod
    def _step_is_back(node: ast.Call) -> bool:
        """Identify FlowSteps that press the hardware/top-navigation BACK key."""
        for kw in node.keywords:
            if kw.arg not in ("screen_return_value", "button_data_selection"):
                continue
            value = kw.value
            if isinstance(value, ast.Name) and value.id == "RET_CODE__BACK_BUTTON":
                return True
            if isinstance(value, ast.Attribute) and value.attr == "RET_CODE__BACK_BUTTON":
                return True
        return False

    def _extract_expected_view(self, node: ast.Call) -> str | None:
        """Extract the first positional arg of FlowStep(...) as the View class name."""
        if not node.args:
            return None

        first_arg = node.args[0]

        # Case 1: FlowStep(MainMenuView, ...)
        if isinstance(first_arg, ast.Name):
            name = first_arg.id
            return self.import_map.get(name, name)

        # Case 2: FlowStep(scan_views.ScanView, ...)
        if isinstance(first_arg, ast.Attribute):
            return first_arg.attr

        return None


def get_flow_test_files() -> list[Path]:
    return sorted(f for f in TESTS_DIR.glob("test_flows*.py") if f.is_file())


def extract_tested_edges() -> list[tuple[str, str, str, bool]]:
    """Parse all flow test files and return tested edges as (source, target, test_name)."""
    all_edges = []

    for test_file in get_flow_test_files():
        try:
            tree = ast.parse(test_file.read_text())
        except Exception as e:
            print(f"ERROR: Failed to parse {test_file}: {e}", file=sys.stderr)
            continue

        resolver = TestImportResolver()
        resolver.visit(tree)

        extractor = FlowTestExtractor(import_map=resolver.import_map)
        extractor._current_file = test_file.stem
        extractor.visit(tree)
        all_edges.extend(extractor.tested_edges)

    return all_edges


# =============================================================================
# Coverage Reconciliation
# =============================================================================

@dataclass
class CoverageReport:
    total_static_edges: int = 0
    total_unique_static_pairs: int = 0
    total_tested_edges: int = 0
    total_unique_tested_pairs: int = 0
    covered_pairs: int = 0
    coverage_percent: float = 0.0
    uncovered: list[dict] = field(default_factory=list)
    tested_only: list[dict] = field(default_factory=list)
    back_to_home_edges: list[dict] = field(default_factory=list)
    clear_history_edges: list[dict] = field(default_factory=list)
    dynamic_edges: list[dict] = field(default_factory=list)


def normalize_target(target: str) -> str:
    """Extract the short class name from a fully-qualified path."""
    if target.startswith("DYNAMIC:"):
        return target
    return target.split(".")[-1]


def _base_view(view_name: str, inheritance: dict[str, str], known_views: set[str]) -> str:
    """Map a tested subclass to the static edge source it inherits."""
    seen = set()
    current = view_name
    while current not in known_views and current in inheritance and current not in seen:
        seen.add(current)
        current = inheritance[current]
    return current


def reconcile(static_edges: list[Edge], tested_raw: list[tuple[str, str, str, bool]]) -> CoverageReport:
    report = CoverageReport()
    report.total_static_edges = len(static_edges)
    report.total_tested_edges = len(tested_raw)

    inheritance = extract_view_inheritance()
    static_sources = {e.source_view for e in static_edges}
    static_targets = {
        normalize_target(e.target_view)
        for e in static_edges
        if normalize_target(e.target_view) != "[BACK]"
        and not normalize_target(e.target_view).startswith("DYNAMIC:")
    }

    # Build static pair set (source, short_target). Back-stack destinations do not
    # have a fixed target until the Controller pops the runtime stack.
    static_pairs: set[tuple[str, str]] = set()
    static_back_sources: set[str] = set()
    for e in static_edges:
        short_target = normalize_target(e.target_view)
        if short_target == "[BACK]":
            static_back_sources.add(e.source_view)
        elif not short_target.startswith("DYNAMIC:"):
            static_pairs.add((e.source_view, short_target))

    # Build tested pair set
    tested_pairs: set[tuple[str, str]] = set()
    tested_back_pairs: set[tuple[str, str]] = set()
    for raw_edge in tested_raw:
        if len(raw_edge) == 3:
            src, tgt, _test_name = raw_edge
            is_back = False
        else:
            src, tgt, _test_name, is_back = raw_edge
        source = _base_view(src, inheritance, static_sources)
        target = _base_view(tgt, inheritance, static_targets)
        pair = (source, target)
        tested_pairs.add(pair)
        if is_back:
            tested_back_pairs.add(pair)

    # A FlowTest records the concrete View popped from the runtime back stack,
    # while the static graph records that branch as [BACK]. Match those edges by
    # the explicit BACK interaction instead of reporting them as tested-only.
    tested_only_pairs = {
        pair for pair in tested_pairs
        if not (pair[0] in static_back_sources and pair in tested_back_pairs)
    }

    report.total_unique_static_pairs = len(static_pairs)
    report.total_unique_tested_pairs = len(tested_pairs)

    covered = static_pairs & tested_pairs
    uncovered = static_pairs - tested_pairs
    tested_only = tested_only_pairs - static_pairs

    report.covered_pairs = len(covered)
    report.coverage_percent = round(len(covered) / len(static_pairs) * 100, 1) if static_pairs else 0.0
    report.uncovered = sorted([{"source": s, "target": t} for s, t in uncovered], key=lambda x: (x["source"], x["target"]))
    report.tested_only = sorted([{"source": s, "target": t} for s, t in tested_only], key=lambda x: (x["source"], x["target"]))

    # Back-to-home irregularities: edges where BACK goes to MainMenuView
    # instead of the natural back stack (i.e. clear_history=True forces home)
    for e in static_edges:
        short_target = normalize_target(e.target_view)
        if e.clear_history:
            report.clear_history_edges.append({
                "source": e.source_view,
                "target": short_target,
                "condition": e.condition,
                "line": e.line_number,
                "method": e.method,
            })

        if e.target_view == "[BACK]" and e.clear_history:
            report.back_to_home_edges.append({
                "source": e.source_view,
                "condition": e.condition,
                "line": e.line_number,
            })

        if short_target.startswith("DYNAMIC:"):
            report.dynamic_edges.append({
                "source": e.source_view,
                "target": short_target,
                "condition": e.condition,
                "line": e.line_number,
            })

    return report


# =============================================================================
# Output Formatters
# =============================================================================

def print_coverage_report(report: CoverageReport):
    print("=" * 70)
    print("  SeedSigner Navigation Coverage Report")
    print("=" * 70)

    print(f"\n  Static edges (from AST):        {report.total_static_edges}")
    print(f"  Unique static pairs:            {report.total_unique_static_pairs}")
    print(f"  Tested edges (from FlowTests):  {report.total_tested_edges}")
    print(f"  Unique tested pairs:            {report.total_unique_tested_pairs}")
    print(f"  Covered pairs:                  {report.covered_pairs}")
    print(f"  Coverage:                       {report.coverage_percent}%")
    print(f"  Uncovered:                      {len(report.uncovered)}")

    if report.uncovered:
        print(f"\n{'─' * 70}")
        print(f"  UNCOVERED EDGES ({len(report.uncovered)})")
        print(f"{'─' * 70}")
        for edge in report.uncovered:
            print(f"  {edge['source']:45s} → {edge['target']}")

    if report.clear_history_edges:
        print(f"\n{'─' * 70}")
        print(f"  CLEAR HISTORY EDGES ({len(report.clear_history_edges)})")
        print(f"  These edges wipe the back stack, forcing the user to MainMenuView.")
        print(f"{'─' * 70}")
        for edge in report.clear_history_edges:
            print(f"  {edge['source']:45s} → {edge['target']}")
            if edge["condition"]:
                print(f"    Condition: {edge['condition'][:80]}")

    if report.dynamic_edges:
        print(f"\n{'─' * 70}")
        print(f"  DYNAMIC/UNRESOLVABLE EDGES ({len(report.dynamic_edges)})")
        print(f"  Cannot be statically matched to test coverage.")
        print(f"{'─' * 70}")
        for edge in report.dynamic_edges:
            print(f"  {edge['source']:45s} → {edge['target']}")

    if report.tested_only:
        print(f"\n{'─' * 70}")
        print(f"  TESTED-ONLY EDGES ({len(report.tested_only)})")
        print(f"  Present in FlowTests but not found in static AST extraction.")
        print(f"  (Sub-Views, mock Views, or back-stack pops not captured statically)")
        print(f"{'─' * 70}")
        for edge in report.tested_only:
            print(f"  {edge['source']:45s} → {edge['target']}")


def print_uncovered(report: CoverageReport):
    for edge in report.uncovered:
        print(f"{edge['source']} → {edge['target']}")


def print_json_report(report: CoverageReport):
    print(json.dumps(asdict(report), indent=4))


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="SeedSigner FlowTest Coverage Analyzer",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--coverage", action="store_true", help="Print the full coverage report")
    group.add_argument("--uncovered", action="store_true", help="List only uncovered edges")
    group.add_argument("--json", action="store_true", help="Output the full report as JSON")

    args = parser.parse_args()

    print("Extracting static edges...", file=sys.stderr)
    static_edges = extract_edges()
    print(f"  Found {len(static_edges)} static edges.", file=sys.stderr)

    print("Extracting tested edges...", file=sys.stderr)
    tested_edges = extract_tested_edges()
    print(f"  Found {len(tested_edges)} tested edges.", file=sys.stderr)

    print("Reconciling coverage...", file=sys.stderr)
    report = reconcile(static_edges, tested_edges)

    if args.coverage:
        print_coverage_report(report)
    elif args.uncovered:
        print_uncovered(report)
    elif args.json:
        print_json_report(report)


if __name__ == "__main__":
    main()

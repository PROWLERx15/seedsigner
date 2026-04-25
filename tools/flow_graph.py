"""
flow_graph.py — minimal navigation-edge extractor for SeedSigner View files.

Walks src/seedsigner/views/tools_views.py with Python's `ast` module, locates
every View subclass, and prints the target class name of each `Destination(...)`
call inside the View's `run()` method.

Run:    python tools/flow_graph.py
Test:   pytest tools/test_flow_graph.py
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = REPO_ROOT / "src" / "seedsigner" / "views" / "tools_views.py"


@dataclass
class Edge:
    source_view: str
    target_view: str


@dataclass
class ViewExtraction:
    name: str
    edges: list[Edge] = field(default_factory=list)


def _is_destination_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "Destination"
    if isinstance(func, ast.Attribute):
        return func.attr == "Destination"
    return False


def _extract_target(node: ast.Call) -> str | None:
    """Return the first-positional or `View_cls=` keyword target name."""
    if node.args:
        first = node.args[0]
        if isinstance(first, ast.Name):
            return first.id
        if isinstance(first, ast.Attribute):
            return first.attr
    for kw in node.keywords:
        if kw.arg == "View_cls":
            if isinstance(kw.value, ast.Name):
                return kw.value.id
            if isinstance(kw.value, ast.Attribute):
                return kw.value.attr
    return None


def _inherits_from_view(class_node: ast.ClassDef) -> bool:
    for base in class_node.bases:
        if isinstance(base, ast.Name) and base.id == "View":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "View":
            return True
    return False


def _find_run_method(class_node: ast.ClassDef) -> ast.FunctionDef | None:
    for child in class_node.body:
        if isinstance(child, ast.FunctionDef) and child.name == "run":
            return child
    return None


def extract_from_file(path: Path) -> list[ViewExtraction]:
    tree = ast.parse(path.read_text())
    results: list[ViewExtraction] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not _inherits_from_view(node):
            continue
        run_fn = _find_run_method(node)
        if run_fn is None:
            continue
        view = ViewExtraction(name=node.name)
        for sub in ast.walk(run_fn):
            if isinstance(sub, ast.Call) and _is_destination_call(sub):
                target = _extract_target(sub)
                if target is not None:
                    view.edges.append(Edge(source_view=node.name, target_view=target))
        results.append(view)
    return results


def main(target: Path = DEFAULT_TARGET) -> int:
    views = extract_from_file(target)
    total = 0
    for view in views:
        print(f"\n{view.name} ({len(view.edges)} edges)")
        for edge in view.edges:
            print(f"  {edge.source_view} -> {edge.target_view}")
        total += len(view.edges)
    print(f"\nTotal edges: {total}  (across {len(views)} View classes in {target.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

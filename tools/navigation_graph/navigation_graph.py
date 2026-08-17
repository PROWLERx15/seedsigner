from dataclasses import dataclass, asdict
import ast
import argparse
import json
import sys
import logging
from pathlib import Path


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
logger.addHandler(handler)

ROOT_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT_DIR / "src"
VIEWS_DIR = SRC_DIR / "seedsigner" / "views"


class ImportResolver(ast.NodeVisitor):
    """
    Collects all imports (both top-level and local function-level) in a file.

    SeedSigner Views frequently use local imports inside `run()` to avoid
    circular dependencies. When we see `Destination(ScanView)`, we need to know
    that `ScanView` resolves to `seedsigner.views.scan_views.ScanView`. This
    visitor builds a mapping of `{local_name: fully_qualified_module_path}`.
    """

    def __init__(self):
        self._import_map: dict[
            str, str
        ] = {}  # e.g. {"ScanView": "seedsigner.views.scan_views.ScanView"}

    def visit_ImportFrom(self, node: ast.ImportFrom):
        # Handle Relative Imports (e.g., `from .view import View`)
        if node.level > 0:
            # node.level == 1 means current package (seedsigner.views)
            base = ".".join(VIEWS_DIR.relative_to(SRC_DIR).parts)

            # If importing a specific module (e.g., `from .seed_views import X`)
            if node.module:
                base = f"{base}.{node.module}"
        else:
            # Absolute Import (e.g., `from seedsigner.views.scan_views import ScanView`)
            base = str(node.module)

        for alias in node.names:
            local_name = alias.asname or alias.name

            # Skip wildcard imports (`from .view import *`) since we can't
            # statically resolve the individual names they pull in.
            if local_name == "*":
                continue

            full_path = f"{base}.{alias.name}"
            self._import_map[local_name] = full_path

        self.generic_visit(node)

    @property
    def import_map(self) -> dict[str, str]:
        return self._import_map


class ViewClassFinder(ast.NodeVisitor):
    """
    Scans a parsed AST to find all classes that inherit from a View subclass.

    How it works:
    SeedSigner uses a strict naming convention where all View classes end with "View".
    We check the base classes (`node.bases`) of every ClassDef. If any base class
    name ends with "View", we record it.

    Note: This skips the base `View` class itself and `BackStackView`,
    because neither of them inherits from a parent View class. This is intended
    behavior since they are routing constructs, not source nodes for our graph.
    """

    def __init__(self):
        # Maps the class name to its raw AST ClassDef node so we can walk its methods later
        self.view_classes: dict[str, ast.ClassDef] = {}

    def _get_name(self, node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        return ""

    def visit_ClassDef(self, node: ast.ClassDef):
        for base in node.bases:
            base_name = self._get_name(base)

            # If the base class ends in "View" (e.g., ErrorView, ScanView, View),
            # this class is a valid View node for our graph.
            if base_name.endswith("View"):
                self.view_classes[node.name] = node
                break  # Stop checking bases once we confirm it's a View

        # Continue traversing in case there are nested classes
        self.generic_visit(node)


@dataclass
class Edge:
    """
    Represents a single directed edge in the navigation graph (a View transition).
    """

    source_view: str  # The class initiating the transition (e.g., "MainMenuView")
    target_view: str  # The destination class (e.g., "ScanView" or "[BACK]")
    condition: str  # The if/elif branch condition (e.g., "if button == SCAN")
    method: str  # The method where this occurred ("run", "__init__", "__post_init__")
    line_number: int  # Line number in the source file
    source_file: str  # The source file path
    is_redirect: bool  # True if this edge was created via set_redirect()
    skip_current_view: bool  # Extracted from Destination(..., skip_current_view=True)
    clear_history: bool  # Extracted from Destination(..., clear_history=True)
    is_trap_risk: bool = False  # True if view has no back button and doesn't skip current view


class DestinationVisitor(ast.NodeVisitor):
    """
    The core engine of the graph extractor.

    This visitor is instantiated for a specific method (e.g., `run()`) inside a
    specific View class. It walks the AST of that method to find `Destination(...)`
    calls, tracking `if/elif/else` conditions along the way to build accurate
    routing edges.
    """

    def __init__(
        self, current_view: str, current_method: str, import_map: dict[str, str]
    ):
        self.current_view = current_view
        self.current_method = current_method
        self._import_map = import_map
        self._edges: list[Edge] = []
        self.disables_back_button = False

        # Acts as a LIFO stack to track which `if` branches we are currently nested inside.
        self._condition_stack: list[str] = []

    def visit_Call(self, node):
        """
        Triggered whenever the AST encounters a function call (e.g., `foo()`).
        We only care about `Destination()` and `self.set_redirect()`.
        """
        # Track if any call within this method sets show_back_button=False
        for kw in node.keywords:
            if kw.arg == "show_back_button" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                self.disables_back_button = True

        # Case 1: Standard Destination(...) call
        if self._is_destination_call(node):
            target_view = self._extract_target_view(node)
            current_condition = " AND ".join(self._condition_stack)
            metadata = self._extract_metadata(node)

            self._add_edge(
                node,
                target_view=target_view,
                is_redirect=False,
                condition=current_condition,
                skip_current_view=metadata["skip_current_view"],
                clear_history=metadata["clear_history"],
            )

        # Case 2: The `set_redirect()` in `__post_init__()` Flow
        elif self._is_set_redirect_call(node):
            # Check the arguments passed to `set_redirect()`
            for arg in node.args:
                if isinstance(arg, ast.Call) and self._is_destination_call(arg):
                    target_view = self._extract_target_view(arg)
                    current_condition = " AND ".join(self._condition_stack)
                    metadata = self._extract_metadata(arg)

                    self._add_edge(
                        node,
                        target_view=target_view,
                        is_redirect=True,
                        condition=current_condition,
                        skip_current_view=metadata["skip_current_view"],
                        clear_history=metadata["clear_history"],
                    )

        self.generic_visit(node)

    def visit_If(self, node: ast.If):
        # convert condition to string
        condition = self._condition_to_str(node.test)

        # IF BLOCK: Push condition to the stack, visit the block, then pop it off
        self._condition_stack.append(condition)
        for child in node.body:
            self.visit(child)
        self._condition_stack.pop()

        # THE ELSE / ELIF BLOCKS
        if node.orelse:
            # Whether it's an 'else' or an 'elif', we are here because the first IF failed.
            # So, we push the negated condition to the stack!
            self._condition_stack.append(f"NOT ({condition})")

            for child in node.orelse:
                self.visit(child)
            # Pop it when we are done looking at the 'else' or 'elif' block
            self._condition_stack.pop()

    def _is_destination_call(self, node: ast.Call) -> bool:
        """Checks if a Call node is a call to `Destination()`"""
        if isinstance(node.func, ast.Name) and node.func.id == "Destination":
            return True
        return False

    def _is_set_redirect_call(self, node: ast.Call) -> bool:
        """Checks if a Call node is a call to `self.set_redirect()`"""

        if isinstance(node.func, ast.Attribute) and node.func.attr == "set_redirect":
            return True

        return False

    def _extract_target_view(self, node: ast.Call) -> str:
        """Extracts the target View class from a Destination() call."""

        if not node.args:
            # Sometimes passed as a keyword argument: Destination(View_cls=ScanView)
            for kw in node.keywords:
                if kw.arg == "View_cls":
                    return self._resolve_name(kw.value)
            return "UNKNOWN_VIEW"

        # Standard first positional argument: Destination(ScanView)
        return self._resolve_name(node.args[0])

    def _resolve_name(self, node) -> str:
        """Converts an AST node into a string representation of the target view."""

        # Case 1: Standard Route -> Destination(SomeView) or BackStackView
        if isinstance(node, ast.Name):
            name = node.id
            if name == "BackStackView":
                return "[BACK]"

            # Look up the actual View class name in our import map.
            return self._import_map.get(name, name)

        # Case 2: Destination(None) defaults to MainMenuView in the Controller
        elif isinstance(node, ast.Constant) and node.value is None:
            return self._import_map.get("MainMenuView", "MainMenuView")

        # Case 3: Dynamic Variables -> Destination(self.next_view)
        try:
            dynamic_target_view = ast.unparse(node).strip()
            return f"DYNAMIC: {dynamic_target_view}"
        except Exception as e:
            return f"UNPARSE_ERROR: {e}"

    def _extract_metadata(self, node: ast.Call) -> dict:
        """Extracts skip_current_view and clear_history from a Destination() call's kwargs."""
        metadata = {"skip_current_view": False, "clear_history": False}

        for kw in node.keywords:
            if isinstance(kw.value, ast.Constant):
                metadata[kw.arg] = kw.value.value

        return metadata

    def _condition_to_str(self, node: ast.If) -> str:
        """Converts an AST condition node back into a readable string."""

        try:
            return ast.unparse(node).strip()
        except Exception as e:
            return f"UNPARSE_ERROR: {e}"

    def _add_edge(
        self,
        node,
        target_view: str | None = None,
        condition: str = "",
        is_redirect: bool = False,
        skip_current_view: bool = False,
        clear_history: bool = False,
    ):
        edge = Edge(
            self.current_view,
            target_view,
            condition,
            self.current_method,
            line_number=node.lineno,
            source_file="",
            is_redirect=is_redirect,
            skip_current_view=skip_current_view,
            clear_history=clear_history,
            is_trap_risk=(self.disables_back_button and not skip_current_view),
        )
        self._edges.append(edge)

    @property
    def edges(self) -> list[Edge]:
        return self._edges

    @property
    def condition_stack(self) -> list[str]:
        return self._condition_stack


def extract_view_files() -> list[Path]:
    """Extracts all view files from the views directory."""

    view_files = []

    for file in VIEWS_DIR.glob("*.py"):
        if file.stem != "__init__":
            view_files.append(file)
    return view_files


def extract_view_inheritance() -> dict[str, str]:
    """Return each View subclass and its direct View base class."""
    inheritance: dict[str, str] = {}

    for view_file in extract_view_files():
        try:
            tree = ast.parse(view_file.read_text())
        except Exception as e:
            logger.error(f"Failed to parse {view_file}: {e}")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            for base in node.bases:
                if isinstance(base, ast.Name) and base.id.endswith("View"):
                    inheritance[node.name] = base.id
                    break

    return inheritance


def extract_edges() -> list[Edge]:
    """
    Loops over all view files, resolves imports, finds View classes,
    and extracts all Destination edges.
    """

    all_edges = []
    view_files = extract_view_files()

    for view_file in view_files:
        try:
            tree = ast.parse(view_file.read_text())
        except Exception as e:
            logger.error(f"Failed to parse {view_file}: {e}")
            continue

        # Resolve imports
        import_resolver = ImportResolver()
        import_resolver.visit(tree)

        # Find View Classes
        class_finder = ViewClassFinder()
        class_finder.visit(tree)

        # Visit each View Class and extract edges
        for class_name, class_node in class_finder.view_classes.items():
            for method_node in class_node.body:
                if isinstance(method_node, ast.FunctionDef) and method_node.name in (
                    "run",
                    "__init__",
                    "__post_init__",
                ):
                    visitor = DestinationVisitor(
                        current_view=class_name,
                        current_method=method_node.name,
                        import_map=import_resolver.import_map,
                    )

                    visitor.visit(method_node)
                    all_edges.extend(visitor.edges)

    return all_edges


# ==============================================================================
# CLI Formatters
# ==============================================================================


def print_json(edges: list[Edge]):
    """Outputs the raw edge data as a JSON array."""
    # asdict converts the dataclass instances to standard dictionaries
    print(json.dumps([asdict(e) for e in edges], indent=4))


def print_dot(edges: list[Edge]):
    """Outputs a Graphviz DOT representation for visual rendering."""
    print("digraph SeedSignerFlow {")
    print('    node [shape=box, style=rounded, fontname="Helvetica"];')
    print('    edge [fontname="Helvetica", fontsize=10];')
    print("")

    for edge in edges:
        cond = edge.condition.replace('"', "'")
        short_target = edge.target_view.split(".")[-1]
        print(f'    "{edge.source_view}" -> "{short_target}" [label="{cond}"];')

    print("}")


def print_report(edges: list[Edge]):
    """Outputs a human-readable text report grouped by source View."""

    # Group edges by source_view
    graph: dict[str, list[Edge]] = {}
    for edge in edges:
        graph.setdefault(edge.source_view, []).append(edge)

    print(f"Navigation Graph Report (Total Edges: {len(edges)})\n{'=' * 60}")

    for source, targets in sorted(graph.items()):
        print(f"\n{source}")
        for edge in targets:
            redirect_flag = " [REDIRECT]" if edge.is_redirect else ""
            trap_flag = " ⚠️ [TRAP RISK]" if edge.is_trap_risk else ""
            short_target = edge.target_view.split(".")[-1]
            print(f"  └──> {short_target}{redirect_flag}{trap_flag}")
            if edge.condition:
                print(f"       Condition: {edge.condition}")

            metadata = []
            if edge.skip_current_view:
                metadata.append("skip_current=True")
            if edge.clear_history:
                metadata.append("clear_history=True")
            if metadata:
                print(f"       Metadata:  {', '.join(metadata)}")

            print(f"       (Line {edge.line_number} in {edge.method})")


def main():
    parser = argparse.ArgumentParser(
        description="SeedSigner Navigation Graph Extractor",
        epilog="Examples:\n  python tools/flow_graph.py --report\n  python tools/flow_graph.py --json > edges.json\n  python tools/flow_graph.py --dot | dot -Tpng > graph.png",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # Require exactly one output format
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--report",
        action="store_true",
        help="Print a human-readable text report to stdout",
    )
    group.add_argument(
        "--json",
        action="store_true",
        help="Print the raw edges as a JSON array to stdout",
    )
    group.add_argument(
        "--dot",
        action="store_true",
        help="Print a Graphviz DOT representation to stdout",
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose debug logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    logger.debug("Starting extraction pipeline...")
    edges = extract_edges()
    logger.debug(f"Extraction complete. Found {len(edges)} edges.")

    if args.json:
        print_json(edges)
    elif args.dot:
        print_dot(edges)
    elif args.report:
        print_report(edges)


if __name__ == "__main__":
    main()

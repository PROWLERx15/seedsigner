import ast
from pathlib import Path

from .flow_tests_extractor import FlowTestExtractor, VerifyFlowTestsSetup
from .models import (
    Edge,
    ExtractedFlowTestSequence,
    ExtractedView,
    FilePaths,
    ParsedFile,
)
from .views_extractor import EdgeExtractor, ImportResolver, ViewExtractor


def get_repository_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "src" / "seedsigner" / "controller.py").exists():
            return parent
    raise FileNotFoundError("Could not locate the SeedSigner repository root")


def get_target_files() -> FilePaths:
    repository_root = get_repository_root()
    src_dir = repository_root / "src"
    views_dir = src_dir / "seedsigner" / "views"
    tests_dir = repository_root / "tests"

    # Extract all files which contains Views in the views directory
    view_files: list[str] = []
    for view_file in views_dir.glob("*.py"):
        if view_file.stem != "__init__":
            view_files.append(str(view_file.relative_to(repository_root)))
    view_files.sort()

    # Extract all FlowTest Files in the tests directory
    test_files: list[str] = []
    for test_file in tests_dir.glob("*.py"):
        if "test_flows" in test_file.stem:
            test_files.append(str(test_file.relative_to(repository_root)))
    test_files.sort()

    return FilePaths(
        repository_root=repository_root,
        controller_module="src/seedsigner/controller.py",
        base_test_module="tests/base.py",
        view_files=view_files,
        test_files=test_files,
    )


def parse_all_target_files(paths: FilePaths) -> dict[str, ParsedFile]:
    parsed_files: dict[str, ParsedFile] = {}

    def parse_file(relative_file_path: str) -> ParsedFile:
        with open(
            paths.repository_root / relative_file_path, "r", encoding="utf-8"
        ) as f:
            file_content = f.read()

        # Parse the contents of the file into an Abstract Syntax Tree (AST)
        tree = ast.parse(file_content, filename=relative_file_path)
        return ParsedFile(relative_file_path, file_content, tree)

    # Parse the Controller module
    parsed_files[paths.controller_module] = parse_file(paths.controller_module)

    # Parse the BaseTest module
    parsed_files[paths.base_test_module] = parse_file(paths.base_test_module)

    # Parse all the View files
    for view_file in paths.view_files:
        parsed_files[view_file] = parse_file(view_file)

    # Parse all the FlowTest files
    for test_file in paths.test_files:
        parsed_files[test_file] = parse_file(test_file)

    return parsed_files


def extract_all_views(
    paths: FilePaths,
    parsed_files: dict[str, ParsedFile],
    target_file: str | None = None,
) -> tuple[dict, int]:

    all_views_by_module = {}
    total_views = 0

    for relative_path in paths.view_files:
        module_name = relative_path.split("/")[-1]
        if target_file and module_name != target_file:
            continue

        parsed_file = parsed_files[relative_path]
        extractor = ViewExtractor(current_module=relative_path)
        extractor.visit(parsed_file.ast_tree)

        if extractor.extracted_views:
            all_views_by_module[relative_path] = extractor.extracted_views
            total_views += len(extractor.extracted_views)

    return all_views_by_module, total_views


def extract_all_edges(
    paths: FilePaths,
    parsed_files: dict[str, ParsedFile],
    target_file: str | None = None,
    target_view: str | None = None,
) -> tuple[dict, int, bool]:

    all_edges_by_module = {}
    total_edges = 0
    found_view = False

    for relative_path in paths.view_files:
        module_name = relative_path.split("/")[-1]
        if target_file and module_name != target_file:
            continue

        parsed_file = parsed_files[relative_path]

        import_resolver = ImportResolver(relative_path)
        import_resolver.visit(parsed_file.ast_tree)

        module_edges = []
        for node in parsed_file.ast_tree.body:
            if (
                isinstance(node, ast.ClassDef)
                and node.name.endswith("View")
                and node.name not in ["View", "BackStackView"]
            ):
                if target_view:
                    if node.name == target_view:
                        found_view = True
                    else:
                        continue

                edge_extractor = EdgeExtractor(
                    current_view=node.name,
                    import_map=import_resolver.import_map,
                    current_module=relative_path,
                )
                edge_extractor.visit(node)
                if edge_extractor.collected_edges:
                    module_edges.extend(edge_extractor.collected_edges)

        if module_edges:
            all_edges_by_module[relative_path] = module_edges
            total_edges += len(module_edges)

    return all_edges_by_module, total_edges, found_view


def extract_all_sequences(
    paths: FilePaths,
    parsed_files: dict[str, ParsedFile],
) -> list[ExtractedFlowTestSequence]:
    # Verify tests/base.py
    base_parsed = parsed_files.get(paths.base_test_module)
    if base_parsed:
        VerifyFlowTestsSetup(paths.base_test_module).visit(base_parsed.ast_tree)

    all_sequences = []

    # Extract from all test_flows_*.py
    for test_file in paths.test_files:
        parsed_file = parsed_files[test_file]
        extractor = FlowTestExtractor(defining_module=test_file)
        extractor.visit(parsed_file.ast_tree)
        all_sequences.extend(extractor.extracted_sequences)

    return all_sequences


def get_all_extracted_data() -> tuple[
    list[ExtractedView], list[Edge], list[ExtractedFlowTestSequence]
]:
    """
    Extracts and returns all views, edges, and test sequences across the entire repository.
    """
    paths = get_target_files()
    parsed_files = parse_all_target_files(paths)

    all_views_by_module, _ = extract_all_views(paths, parsed_files)
    all_edges_by_module, _, _ = extract_all_edges(paths, parsed_files)
    all_sequences = extract_all_sequences(paths, parsed_files)

    all_views = []
    for views in all_views_by_module.values():
        all_views.extend(views)

    all_edges = []
    for edges in all_edges_by_module.values():
        all_edges.extend(edges)

    return all_views, all_edges, all_sequences

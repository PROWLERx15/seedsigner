import argparse
import sys

from .coverage_checker import CoverageAnalyzer
from .helpers import (
    extract_all_edges,
    extract_all_views,
    get_all_extracted_data,
    get_target_files,
    parse_all_target_files,
)
from .report_generator import JSONReport, TextReport


class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


def display_all_views(target_file: str = None):
    try:
        paths = get_target_files()
        parsed_files = parse_all_target_files(paths)
    except Exception as e:
        print(f"{Colors.FAIL}{Colors.BOLD}Error loading source files: {e}{Colors.ENDC}")
        sys.exit(1)

    all_views_by_module, total_views = extract_all_views(
        paths, parsed_files, target_file
    )

    box_width = 57
    title_views = "SeedSigner Analyzer - Views".center(box_width)
    print(f"\n{Colors.BOLD}{Colors.CYAN}╭{'─' * box_width}╮{Colors.ENDC}")
    print(
        f"{Colors.BOLD}{Colors.CYAN}│{Colors.ENDC}{Colors.BOLD}{title_views}{Colors.ENDC}{Colors.BOLD}{Colors.CYAN}│{Colors.ENDC}"
    )
    print(f"{Colors.BOLD}{Colors.CYAN}╰{'─' * box_width}╯{Colors.ENDC}\n")

    print(
        f"{Colors.BOLD}Total Views found: {Colors.GREEN}{total_views}{Colors.ENDC} {Colors.BOLD}across {Colors.GREEN}{len(all_views_by_module)}{Colors.ENDC} {Colors.BOLD}files{Colors.ENDC}\n"
    )

    for module, views in all_views_by_module.items():
        module_name = module.split("/")[-1]
        print(
            f"{Colors.BOLD}{Colors.BLUE}▶ Views from {module_name}{Colors.ENDC} {Colors.DIM}({len(views)} views){Colors.ENDC}"
        )
        for view in views:
            base_classes = (
                ", ".join(view.base_class_names) if view.base_class_names else "None"
            )
            print(
                f"  {Colors.DIM}·{Colors.ENDC} {Colors.BOLD}{view.view_class_name:<40}{Colors.ENDC} {Colors.DIM}inherits: {base_classes}{Colors.ENDC}"
            )
        print()


def display_all_edges(target_file: str = None, target_view: str = None):
    try:
        paths = get_target_files()
        parsed_files = parse_all_target_files(paths)
    except Exception as e:
        print(f"{Colors.FAIL}{Colors.BOLD}Error loading source files: {e}{Colors.ENDC}")
        sys.exit(1)

    all_edges_by_module, total_edges, found_view = extract_all_edges(
        paths, parsed_files, target_file, target_view
    )

    if target_view and not found_view:
        print(
            f"{Colors.WARNING}View '{target_view}' not found in the parsed files.{Colors.ENDC}"
        )
        sys.exit(1)

    box_width = 57
    title_edges = "SeedSigner Analyzer - Edges".center(box_width)
    print(f"\n{Colors.BOLD}{Colors.CYAN}╭{'─' * box_width}╮{Colors.ENDC}")
    print(
        f"{Colors.BOLD}{Colors.CYAN}│{Colors.ENDC}{Colors.BOLD}{title_edges}{Colors.ENDC}{Colors.BOLD}{Colors.CYAN}│{Colors.ENDC}"
    )
    print(f"{Colors.BOLD}{Colors.CYAN}╰{'─' * box_width}╯{Colors.ENDC}\n")

    print(
        f"{Colors.BOLD}Total Edges found: {Colors.GREEN}{total_edges}{Colors.ENDC} {Colors.BOLD}across {Colors.GREEN}{len(all_edges_by_module)}{Colors.ENDC} {Colors.BOLD}files{Colors.ENDC}\n"
    )

    for module, edges in all_edges_by_module.items():
        module_name = module.split("/")[-1]
        print(
            f"{Colors.BOLD}{Colors.BLUE}▶ {module_name}{Colors.ENDC} {Colors.DIM}({len(edges)} edges){Colors.ENDC}"
        )

        # Group edges by source_view for cleaner hierarchical output
        edges_by_source = {}
        for edge in edges:
            if edge.source_view not in edges_by_source:
                edges_by_source[edge.source_view] = []
            edges_by_source[edge.source_view].append(edge)

        for source_view, source_edges in edges_by_source.items():
            print(
                f"\n  {Colors.BOLD}{source_view}{Colors.ENDC} {Colors.BOLD}{Colors.FAIL}[SOURCE VIEW]{Colors.ENDC}"
            )
            print("  │")
            for i, edge in enumerate(source_edges):
                is_last = i == len(source_edges) - 1
                prefix = "└──▶" if is_last else "├──▶"

                short_target_view = edge.target_view.split(".")[-1]
                print(
                    f"  {prefix} {Colors.BOLD}{short_target_view}{Colors.ENDC} {Colors.BOLD}{Colors.FAIL}[TARGET VIEW]{Colors.ENDC} {Colors.DIM}(Line {edge.line_number}){Colors.ENDC}"
                )

                indent = "    " if is_last else "│   "

                if edge.condition:
                    print(f"  {indent} {Colors.CYAN}Conditions:{Colors.ENDC}")
                    conditions = edge.condition.split(" AND ")
                    for cond in conditions:
                        print(
                            f"  {indent}   {Colors.DIM}·{Colors.ENDC} {Colors.WARNING}{cond}{Colors.ENDC}"
                        )

                # Add vertical gap between edges for readability
                if not is_last:
                    print("  │")
        print()


class AnalyzerArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        if "invalid choice" in message:
            try:
                invalid_cmd = message.split("'")[1]
                print(
                    f"{Colors.FAIL}analyzer.cli: '{invalid_cmd}' is not an analyzer command. See 'python3 -m tools.analyzer.cli --help'.{Colors.ENDC}"
                )
            except Exception:
                print(f"{Colors.FAIL}analyzer.cli: error: {message}{Colors.ENDC}")
        elif "unrecognized arguments" in message:
            try:
                args_passed = message.split(": ")[1]
                print(
                    f"{Colors.FAIL}analyzer.cli: {args_passed} is not an analyzer command. See 'python3 -m tools.analyzer.cli --help'.{Colors.ENDC}"
                )
            except Exception:
                print(f"{Colors.FAIL}analyzer.cli: error: {message}{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}analyzer.cli: error: {message}{Colors.ENDC}")
        sys.exit(1)


def main():
    main_desc = f"""
{Colors.BOLD}NAME{Colors.ENDC}
    analyzer.cli - SeedSigner Analyzer

{Colors.BOLD}SYNOPSIS{Colors.ENDC}
    ./analyzer <command> [<args>]

{Colors.BOLD}DESCRIPTION{Colors.ENDC}
    Statically analyzes the SeedSigner codebase to extract the internal
    navigation routing graph. It parses AST (Abstract Syntax Trees) to identify
    all 'View' subclasses and tracks their transitions via 'Destination' and
    'set_redirect' calls, including the logical conditions required to trigger
    each transition.
"""

    parser = AnalyzerArgumentParser(
        description=main_desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=True,
    )

    subparsers = parser.add_subparsers(
        dest="command", title=f"{Colors.BOLD}COMMANDS{Colors.ENDC}", metavar=""
    )

    views_desc = f"""
{Colors.BOLD}DESCRIPTION{Colors.ENDC}
    Extracts and prints all View classes found in the codebase.
    The output is grouped by the file in which the views are defined.
"""
    views_parser = subparsers.add_parser(
        "get-all-views",
        help="Print all views grouped by file",
        description=views_desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    views_parser.add_argument(
        "--file",
        type=str,
        help="Filter output to a specific file (e.g., seed_views or seed_views.py)",
    )

    edges_desc = f"""
{Colors.BOLD}DESCRIPTION{Colors.ENDC}
    Extracts and prints all transition edges found in the codebase.
    The output is grouped by file, and hierarchical by the source View.
"""
    edges_parser = subparsers.add_parser(
        "get-all-edges",
        help="Print all edges grouped by file",
        description=edges_desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    edges_parser.add_argument(
        "--view",
        type=str,
        help="Filter output to a specific view (must end with 'View')",
    )
    edges_parser.add_argument(
        "--file",
        type=str,
        help="Filter output to a specific file (e.g., seed_views or seed_views.py)",
    )

    report_desc = f"""
{Colors.BOLD}DESCRIPTION{Colors.ENDC}
    Generates a full analyzer report containing all extracted views and edges.
"""
    report_parser = subparsers.add_parser(
        "generate-report",
        help="Generate a full analyzer report",
        description=report_desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    report_parser.add_argument(
        "--json",
        action="store_true",
        help="Generate the report in JSON format",
    )
    report_parser.add_argument(
        "--text",
        action="store_true",
        help="Generate the report in Text format",
    )

    coverage_desc = f"""
{Colors.BOLD}DESCRIPTION{Colors.ENDC}
    Calculates and prints the FlowTest coverage of navigation edges.
"""
    coverage_parser = subparsers.add_parser(
        "get-coverage",
        help="Print test coverage statistics",
        description=coverage_desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    coverage_parser.add_argument(
        "--include-negative-assertions",
        action="store_true",
        help="Include edges covered in `pytest.raises` blocks",
    )
    coverage_parser.add_argument(
        "--view",
        type=str,
        help="Filter output to a specific view (must end with 'View')",
    )
    coverage_parser.add_argument(
        "--file",
        type=str,
        help="Filter output to a specific file (e.g., seed_views or seed_views.py)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if getattr(args, "view", None) and not args.view.endswith("View"):
        print(
            f"{Colors.FAIL}{Colors.BOLD}Error: The --view argument must end with 'View'.{Colors.ENDC}"
        )
        sys.exit(1)

    target_file = getattr(args, "file", None)
    if target_file:
        if not target_file.endswith(".py"):
            target_file += ".py"

        try:
            paths = get_target_files()
            file_found = any(target_file in path for path in paths.view_files)
            if not file_found:
                print(
                    f"{Colors.WARNING}File '{target_file}' not found in the views directory.{Colors.ENDC}"
                )
                sys.exit(1)
        except Exception:
            pass  # allow the main functions to handle the overall load error

    if args.command == "get-all-views":
        display_all_views(target_file=target_file)
    elif args.command == "get-all-edges":
        display_all_edges(
            target_file=target_file, target_view=getattr(args, "view", None)
        )
    elif args.command == "generate-report":
        if args.json:
            try:
                all_views, all_edges, all_sequences = get_all_extracted_data()
                coverage = CoverageAnalyzer(
                    all_views, all_edges, all_sequences
                ).reconcile()
                output_path = JSONReport().generate_json_report(
                    all_views, all_edges, coverage
                )
                print(
                    f"{Colors.GREEN}JSON report successfully generated at: {Colors.ENDC}{output_path}"
                )
                sys.exit(0)

            except Exception as e:
                print(
                    f"{Colors.FAIL}{Colors.BOLD}Error generating JSON report: {e}{Colors.ENDC}"
                )
                sys.exit(1)
        elif args.text:
            try:
                all_views, all_edges, all_sequences = get_all_extracted_data()
                coverage = CoverageAnalyzer(
                    all_views, all_edges, all_sequences
                ).reconcile()
                output_path = TextReport().generate_text_report(
                    all_views, all_edges, coverage
                )
                print(
                    f"{Colors.GREEN}Text report successfully generated at: {Colors.ENDC}{output_path}"
                )
                sys.exit(0)

            except Exception as e:
                print(
                    f"{Colors.FAIL}{Colors.BOLD}Error generating Text report: {e}{Colors.ENDC}"
                )
                sys.exit(1)
        else:
            print(
                f"{Colors.FAIL}{Colors.BOLD}Error: You must specify --json or --text when generating a report.{Colors.ENDC}"
            )
            sys.exit(1)

    elif args.command == "get-coverage":
        try:
            all_views, all_edges, all_sequences = get_all_extracted_data()
            include_neg = getattr(args, "include_negative_assertions", False)
            coverage = CoverageAnalyzer(
                all_views,
                all_edges,
                all_sequences,
                include_negative_assertions=include_neg,
            ).reconcile()

            target_file = getattr(args, "file", None)
            if target_file and not target_file.endswith(".py"):
                target_file += ".py"
            target_view = getattr(args, "view", None)

            view_to_file = {
                v.view_class_name: v.defining_module.split("/")[-1] for v in all_views
            }

            filtered_covered = []
            for src, tgt in coverage["covered_edges"]:
                if target_view and src != target_view:
                    continue
                if target_file and target_file not in view_to_file.get(src, ""):
                    continue
                filtered_covered.append((src, tgt))

            filtered_untested_list = []
            for src, tgt in coverage["untested_edges"]:
                if target_view and src != target_view:
                    continue
                if target_file and target_file not in view_to_file.get(src, ""):
                    continue
                filtered_untested_list.append((src, tgt))

            filtered_unresolved_list = []
            for src, tgt in coverage["unresolved_pairs"]:
                if target_view and src != target_view:
                    continue
                if target_file and target_file not in view_to_file.get(src, ""):
                    continue
                filtered_unresolved_list.append((src, tgt))

            tested_edges_count = len(filtered_covered)
            untested_count = len(filtered_untested_list)
            total_edges_count = tested_edges_count + untested_count
            percentage = (
                round((tested_edges_count / total_edges_count) * 100, 1) if total_edges_count else 100.0
            )

            box_width = 57
            title = "SeedSigner Analyzer - Coverage".center(box_width)
            print(f"\n{Colors.BOLD}{Colors.CYAN}╭{'─' * box_width}╮{Colors.ENDC}")
            print(
                f"{Colors.BOLD}{Colors.CYAN}│{Colors.ENDC}{Colors.BOLD}{title}{Colors.ENDC}{Colors.BOLD}{Colors.CYAN}│{Colors.ENDC}"
            )
            print(f"{Colors.BOLD}{Colors.CYAN}╰{'─' * box_width}╯{Colors.ENDC}\n")

            print(f"  Total Edges:    {Colors.BOLD}{total_edges_count}{Colors.ENDC}")
            print(f"  Tested Edges:   {Colors.BOLD}{tested_edges_count}{Colors.ENDC}")
            print(
                f"  Coverage:       {Colors.BOLD}{Colors.GREEN}{percentage}%{Colors.ENDC}"
            )
            print(f"  Untested Edges: {Colors.BOLD}{untested_count}{Colors.ENDC}")

            if untested_count == 0 and total_edges_count > 0:
                print(
                    f"\n  {Colors.BOLD}{Colors.GREEN}🎉 100% Coverage! All {total_edges_count} edges are covered by FlowTests.{Colors.ENDC}"
                )
            if filtered_untested_list:
                untested_by_src = {}
                for src, tgt in filtered_untested_list:
                    untested_by_src.setdefault(src, []).append(tgt)

                print(f"\n{Colors.BOLD}{Colors.BLUE}▶ UNTESTED EDGES{Colors.ENDC}")
                for src, tgts in sorted(untested_by_src.items()):
                    print(f"\n  {Colors.BOLD}{Colors.WARNING}{src}{Colors.ENDC}")
                    for tgt in sorted(tgts):
                        print(
                            f"    {Colors.DIM}·{Colors.ENDC} {src} {Colors.DIM}──▶{Colors.ENDC} {tgt}"
                        )

            if filtered_unresolved_list:
                unresolved_by_src = {}
                for src, tgt in filtered_unresolved_list:
                    unresolved_by_src.setdefault(src, []).append(tgt)

                print(
                    f"\n{Colors.BOLD}{Colors.BLUE}▶ UNRESOLVED TEST PAIRS{Colors.ENDC}"
                )
                for src, tgts in sorted(unresolved_by_src.items()):
                    print(f"\n  {Colors.BOLD}{Colors.WARNING}{src}{Colors.ENDC}")
                    for tgt in sorted(tgts):
                        print(
                            f"    {Colors.DIM}·{Colors.ENDC} {src} {Colors.DIM}──▶{Colors.ENDC} {tgt}"
                        )

        except Exception as e:
            print(
                f"{Colors.FAIL}{Colors.BOLD}Error calculating coverage: {e}{Colors.ENDC}"
            )
            sys.exit(1)


if __name__ == "__main__":
    main()

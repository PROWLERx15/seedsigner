# Phase 1 Completion: Static Navigation Graph Analyzer

## Accomplishments
- Implemented a static analyzer using Python's `ast` module to extract the SeedSigner navigation graph directly from the View layer without executing the code.
- Successfully mapped 293 unique navigational edges across the codebase.
- Resolved dynamic routing conditions by tracking `if/elif/else` stacks to properly label edges with their exact requirements.
- Implemented automated visual SVG generation categorized by module (Scan, PSBT, Seed, Settings, etc.).

## Architecture
The pipeline (`tools/navigation_graph/navigation_graph.py`) uses three primary components:
1. **ImportResolver**: Builds an `import_map` from the AST to resolve short View names to their fully qualified paths, handling local function-level imports.
2. **ViewClassFinder**: Identifies all classes inheriting from `View`, filtering out base and render-only screens.
3. **DestinationVisitor**: Parses `run()`, `__init__()`, and `__post_init__()` across all Views. 
   - Intercepts `Destination()` returns and `self.set_redirect()` calls.
   - Maintains a Condition Stack (`self._condition_stack`) to apply complex `NOT` conditions for `else` branches.
   - Extracts metadata like `skip_current_view` and `clear_history`.

## Deliverables
All deliverables are located in `tools/navigation_graph/`:

1. **`navigation_graph.py`**: The core CLI.
   - `--report`: Generates a hierarchical text tree (saved to `outputs/navigation_report.txt`).
   - `--json`: Outputs JSON for CI/CD validation (saved to `outputs/navigation_edges.json`).
   - `--dot`: Generates raw DOT graph (saved to `outputs/dot_graph.txt`).
2. **`generate_dot_graph.py`**: A post-processing script that reads `outputs/dot_graph.txt` and clusters the edges by module.
3. **`graphs/` Directory**: Contains the separated `.dot` and `.svg` files (e.g., `scan.svg`, `psbt.svg`).

## Phase 2 Focus
- Implement the Test Edge Extractor to parse `tests/test_flows_*.py`.
- Build the reconciliation engine to map test sequences against the static graph and calculate exact test coverage percentages.
- Write dedicated unit tests for the AST analyzer tool itself.
- Verify the generated graph accuracy manually against the live SeedSigner device/emulator.

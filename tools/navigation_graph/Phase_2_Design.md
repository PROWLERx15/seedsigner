# Phase 2: Flow Test Coverage Reconciliation Engine

## 1. What is a FlowTest?

A FlowTest is SeedSigner's mechanism for testing navigation paths without running on real hardware. It works by mocking the entire Screen layer (pixels, buttons, hardware) and exercising the View → Controller → View routing loop in pure Python.

### The Two Core Classes

**`FlowStep`** (defined in [tests/base.py](file:///home/kshitij/CODE/SeedSigner/seedsigner/tests/base.py#L124-L143)):

```python
@dataclass
class FlowStep:
    expected_view: type[View] = None          # Which View class should be active at this step
    before_run: Callable[[View], None] = None  # Optional setup function (e.g., inject QR data)
    screen_return_value: int | str = None       # Mock the raw Screen return (e.g., button index 0)
    button_data_selection: str | tuple = None   # Mock a named button press (e.g., MainMenuView.SCAN)
    is_redirect: bool = False                   # Expect a redirect (skip_current_view=True)
```

**`FlowTest`** (defined in [tests/base.py](file:///home/kshitij/CODE/SeedSigner/seedsigner/tests/base.py#L175-L306)):

The base class that provides `run_sequence(sequence: list[FlowStep])`. This method:
1. Patches `Destination._run_view()` to intercept every View instantiation.
2. Patches `View.run_screen()` to inject mocked user input without needing a real screen.
3. Walks through each `FlowStep` in order, asserting that the Controller routes to the expected View.
4. If at any step the actual View class doesn't match `expected_view`, it raises `FlowTestUnexpectedViewException`.

### Walkthrough: A Complete FlowTest Example

From [tests/test_flows.py](file:///home/kshitij/CODE/SeedSigner/seedsigner/tests/test_flows.py#L23-L33):

```python
def test_simple_flow(self):
    self.run_sequence([
        FlowStep(MainMenuView, button_data_selection=MainMenuView.TOOLS),
        FlowStep(ToolsMenuView, button_data_selection=ToolsMenuView.KEYBOARD),
        FlowStep(ToolsCalcFinalWordNumWordsView, button_data_selection=ToolsCalcFinalWordNumWordsView.TWELVE),
        FlowStep(SeedMnemonicEntryView),
    ])
```

What happens at runtime:

```
Step 1: Controller instantiates MainMenuView
        → FlowTest asserts View_cls == MainMenuView              ✓
        → Mocked Screen returns index of "Tools" button
        → MainMenuView.run() returns Destination(ToolsMenuView)

Step 2: Controller instantiates ToolsMenuView
        → FlowTest asserts View_cls == ToolsMenuView             ✓
        → Mocked Screen returns index of "Keyboard" button
        → ToolsMenuView.run() returns Destination(ToolsCalcFinalWordNumWordsView)

Step 3: Controller instantiates ToolsCalcFinalWordNumWordsView
        → FlowTest asserts View_cls == ToolsCalcFinalWordNumWordsView  ✓
        → Mocked Screen returns index of "12 words" button
        → run() returns Destination(SeedMnemonicEntryView)

Step 4: Controller instantiates SeedMnemonicEntryView
        → FlowTest asserts View_cls == SeedMnemonicEntryView     ✓
        → No more steps, test stops.
```

Each consecutive pair of `FlowStep.expected_view` values represents a **tested navigation edge**:
- `MainMenuView → ToolsMenuView`
- `ToolsMenuView → ToolsCalcFinalWordNumWordsView`
- `ToolsCalcFinalWordNumWordsView → SeedMnemonicEntryView`

This is the key insight: **consecutive FlowStep pairs are tested edges.**

### Advanced FlowTest Patterns

**Redirects** — Some Views redirect immediately in `__init__` or `__post_init__` without calling `run()`. The test marks these with `is_redirect=True`:

```python
FlowStep(SeedsMenuView, is_redirect=True),  # No seeds loaded → auto-redirect to LoadSeedView
FlowStep(LoadSeedView, button_data_selection=LoadSeedView.TYPE_12WORD),
```

**Before-run hooks** — Views that depend on external state (like QR scanner data) use `before_run` to inject data:

```python
def load_seed_into_decoder(view):
    view.decoder.add_data("0000" * 11 + "0003")

FlowStep(ScanView, before_run=load_seed_into_decoder),
```

**Back button navigation** — The Controller maintains a back stack. Tests exercise this with `RET_CODE__BACK_BUTTON`:

```python
FlowStep(PowerOptionsView, screen_return_value=RET_CODE__BACK_BUTTON),
FlowStep(MainMenuView),  # Popped from back stack
```

### Where the Flow Tests Live

| File | Domain | Tests |
|------|--------|-------|
| `tests/test_flows.py` | Core FlowTest framework verification | 9 |
| `tests/test_flows_seed.py` | Seed creation, backup, signing, xpub export | 12 |
| `tests/test_flows_psbt.py` | PSBT scanning, signing, address verification | — |
| `tests/test_flows_tools.py` | Dice, image, keyboard entropy tools | — |
| `tests/test_flows_settings.py` | Settings navigation | — |
| `tests/test_flows_view.py` | Base view behaviors | — |
| `tests/test_flows_l10n.py` | Localization flows | — |


## 2. Expected Outcomes from Phase 2

The deliverable is a reconciliation engine that answers one question: **"Which navigation edges in the codebase have FlowTests and which don't?"**

Concrete outputs:

1. **Tested edge set** — Parse all `test_flows_*.py` files, extract consecutive `FlowStep.expected_view` pairs, produce a set of `(SourceView, TargetView)` tuples that have test coverage.

2. **Coverage report** — Compare tested edges against the static graph from Phase 1. Output:
   - Total static edges (from `navigation_graph.py`)
   - Total tested edges (from flow test extraction)
   - Total matched edges (intersection)
   - Coverage percentage
   - Explicit list of uncovered edges

3. **CLI flags** — Extend the existing CLI:
   - `--coverage` — Print the coverage report
   - `--uncovered` — List only uncovered edges

4. **Machine-readable output** — JSON format for CI consumption:
   ```json
   {
     "total_static_edges": 293,
     "total_tested_edges": 87,
     "coverage_percent": 29.7,
     "uncovered": [
       {"source": "ScanView", "target": "NotYetImplementedView", "condition": "..."},
       ...
     ]
   }
   ```

5. **Unit tests** — Dedicated tests for the AST analyzer itself using synthetic View files with known edges, verifying the extractor produces exactly the expected output.


## 3. Architecture

### High-Level Pipeline

```
┌──────────────────────────┐     ┌──────────────────────────┐
│ Phase 1 (existing)       │     │ Phase 2 (new)            │
│                          │     │                          │
│ View files (*.py)        │     │ test_flows_*.py          │
│         │                │     │         │                │
│         ▼                │     │         ▼                │
│ navigation_graph.py      │     │ FlowTestExtractor        │
│  ├─ ImportResolver       │     │  (new AST visitor)       │
│  ├─ ViewClassFinder      │     │         │                │
│  └─ DestinationVisitor   │     │         ▼                │
│         │                │     │ Tested Edge Set          │
│         ▼                │     │ {(View_A, View_B), ...}  │
│ Static Edge Set          │     │                          │
│ {(View_A, View_B,cond)}  │     └────────────┬─────────────┘
│                          │                   │
└────────────┬─────────────┘                   │
             │                                 │
             └─────────────┬───────────────────┘
                           │
                           ▼
                   CoverageReconciler
                   ├─ Match tested ↔ static
                   ├─ Compute coverage %
                   └─ Output report/JSON
```

### Component Design

#### 3.1. `FlowTestExtractor` (new)

An AST-based visitor that parses `tests/test_flows_*.py` files. It:
1. Finds all classes inheriting from `FlowTest`.
2. Finds all methods starting with `test_`.
3. Inside each test method, locates all calls to `self.run_sequence(...)`.
4. Extracts the `FlowStep` list argument from each `run_sequence` call.
5. From each `FlowStep`, extracts the `expected_view` argument.
6. Produces consecutive pairs `(FlowStep_n.expected_view, FlowStep_n+1.expected_view)` as tested edges.

The core logic:

```python
class FlowTestExtractor(ast.NodeVisitor):
    """Extracts tested navigation edges from FlowTest sequences."""

    def __init__(self, import_map: dict):
        self.import_map = import_map
        self.tested_edges: set[tuple[str, str]] = set()

    def visit_Call(self, node: ast.Call):
        if self._is_run_sequence_call(node):
            steps = self._extract_flowsteps(node)
            for i in range(len(steps) - 1):
                source = steps[i]
                target = steps[i + 1]
                if source and target:
                    self.tested_edges.add((source, target))
        self.generic_visit(node)

    def _extract_flowsteps(self, node: ast.Call) -> list[str]:
        """Extract the expected_view from each FlowStep in the sequence."""
        views = []
        # The sequence is either the first positional arg or the `sequence=` kwarg
        seq_arg = self._find_sequence_arg(node)
        if not seq_arg or not isinstance(seq_arg, ast.List):
            return views

        for elt in seq_arg.elts:
            if isinstance(elt, ast.Call):
                view_name = self._extract_expected_view(elt)
                views.append(view_name)
        return views
```

#### 3.2. `CoverageReconciler` (new)

A pure data comparison module:

```python
class CoverageReconciler:
    def __init__(self, static_edges: list[Edge], tested_edges: set[tuple[str, str]]):
        self.static_edges = static_edges
        self.tested_edges = tested_edges

    def compute(self) -> CoverageReport:
        # Normalize static edges to (short_source, short_target) pairs
        static_pairs = {(e.source_view, e.target_view.split('.')[-1]) for e in self.static_edges}

        covered = static_pairs & self.tested_edges
        uncovered = static_pairs - self.tested_edges

        return CoverageReport(
            total_static=len(static_pairs),
            total_tested=len(self.tested_edges),
            total_covered=len(covered),
            coverage_pct=len(covered) / len(static_pairs) * 100,
            uncovered_edges=uncovered,
        )
```

#### 3.3. Edge Matching Strategy

The matching between static edges and tested edges operates on **short class names only**, not fully qualified paths.

Static edge: `("ScanView", "seedsigner.views.seed_views.SeedFinalizeView", "condition...")`
→ Normalized to: `("ScanView", "SeedFinalizeView")`

Tested edge: `("ScanView", "SeedFinalizeView")`
→ Already short names.

A match is: `static_normalized == tested_pair`.

Condition strings are NOT matched. If the static graph has 5 edges from `ScanView → SeedFinalizeView` under different conditions, and the test suite has at least one `ScanView → SeedFinalizeView` transition, all 5 static edges are considered "partially covered" but the report will note that only the _transition_ is covered, not necessarily all _conditions_.

#### 3.4. Handling Edge Cases

| Case | Handling |
|------|----------|
| `FlowStep` with `is_redirect=True` | Still counts as a tested edge to the next step |
| `RET_CODE__BACK_BUTTON` leading to back stack pop | The next `FlowStep` shows where the back stack goes; recorded as a tested edge |
| Dynamic `before_run` setup | Irrelevant to edge extraction; we only care about `expected_view` |
| `FlowStep` with no `expected_view` | Skip it |
| Same edge tested in multiple test files | Deduplicated in the tested edge set |
| Static edge with `[BACK]` as target | Cannot be matched to a specific tested edge; reported separately |
| Static edge with `DYNAMIC:` target | Cannot be matched; reported as "unresolved" |


## 4. File Structure

```
tools/navigation_graph/
├── navigation_graph.py          # Phase 1: static edge extractor (existing)
├── flow_test_extractor.py       # Phase 2: FlowTest edge parser (new)
├── coverage.py                  # Phase 2: reconciliation engine (new)
├── generate_dot_graph.py        # Visualization script (existing)
├── Report.md                    # Project status (existing, will be updated)
├── outputs/                     # Raw generated data
│   ├── navigation_report.txt
│   ├── navigation_edges.json
│   ├── dot_graph.txt
│   └── coverage_report.json     # (new)
└── graphs/
    ├── dot/
    └── svg/
```

## 5. Verification Plan

### Unit Tests for the AST Analyzer

Create synthetic View files with known, hand-counted edges. Run the extractor and assert the output matches exactly.

```
tests/test_navigation_graph.py
├── test_simple_destination_extraction
├── test_conditional_branch_extraction
├── test_redirect_extraction
├── test_local_import_resolution
├── test_backstack_view_handling
└── test_dynamic_target_labeling
```

### Unit Tests for the FlowTest Extractor

Create synthetic test files with known `FlowStep` sequences. Run the extractor and assert the correct edges are produced.

```
tests/test_flow_test_extractor.py
├── test_simple_sequence_extraction
├── test_redirect_step_extraction
├── test_multiple_run_sequence_calls
├── test_back_button_edge
└── test_sequence_in_kwarg
```

### Manual Verification

Pick 3-5 specific Views and manually trace their `run()` method to verify the static extractor output matches. Then check the corresponding flow tests to verify the coverage report is accurate.

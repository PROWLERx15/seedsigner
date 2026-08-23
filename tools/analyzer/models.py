import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FilePaths:
    """
    Represents the repository paths and target files to be analyzed.
    """

    repository_root: Path
    controller_module: str
    base_test_module: str
    view_files: list[str]
    test_files: list[str]


@dataclass
class ParsedFile:
    """
    Represents a target file parsed into an Abstract Syntax Tree (AST).
    """

    file_path: str
    file_content: str
    ast_tree: ast.Module


@dataclass
class ExtractedView:
    """
    Represents a View class extracted from the AST (View Files).
    """

    view_class_name: str
    defining_module: str
    base_class_names: list[str]
    method_names: list[str]


@dataclass
class ExtractedFlowStep:
    """
    Represents a single step within a FlowTest sequence.
    """

    expected_view: str
    is_back_button_interaction: bool = False
    is_exception_interaction: bool = False


@dataclass
class ExtractedFlowTestSequence:
    """
    Represents an entire sequence of FlowSteps passed to run_sequence().
    """

    steps: list[ExtractedFlowStep]
    is_negative_assertion: bool
    defining_module: str
    test_name: str
    line_number: int


@dataclass
class Edge:
    """
    Represents a single directed edge in the navigation graph (a View transition).
    Eg. MainMenuView -> ScanView
    """

    source_view: str
    target_view: str
    condition: str
    method: str
    line_number: int
    source_file: str
    is_redirect: bool
    skip_current_view: bool
    clear_history: bool
    is_trap_risk: bool = False

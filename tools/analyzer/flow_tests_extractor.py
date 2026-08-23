import ast

from .models import ExtractedFlowStep, ExtractedFlowTestSequence


class VerifyFlowTestsSetup(ast.NodeVisitor):
    """
    Validates that the `tests/base.py` test harness matches our expectations.
    Ensures that `FlowStep` has the expected dataclass fields and that
    `FlowTest.run_sequence` takes `sequence` as its first parameter.
    """

    def __init__(self, base_test_module):
        self.base_test_module = base_test_module

    def visit_ClassDef(self, node: ast.ClassDef):
        if node.name == "FlowStep":
            fields = []
            for item in node.body:
                # Dataclass fields are stored as 'Annotated Assignments' (e.g. expected_view: type)
                if isinstance(item, ast.AnnAssign) and isinstance(
                    item.target, ast.Name
                ):
                    fields.append(item.target.id)

            # dataclass fields are not in order in AST
            expected_fields = [
                "expected_view",
                "before_run",
                "screen_return_value",
                "button_data_selection",
                "is_redirect",
            ]
            if set(fields) != set(expected_fields):
                raise ValueError(
                    f"Class FlowStep has been modified! Expected {expected_fields}, got {fields}"
                )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if node.name == "run_sequence":
            # args[0] is 'self', so args[1] must be 'sequence'
            if len(node.args.args) < 2 or node.args.args[1].arg != "sequence":
                raise ValueError(
                    "FlowTest.run_sequence must take 'sequence' as its first parameter after 'self'"
                )

        self.generic_visit(node)


class FlowTestExtractor(ast.NodeVisitor):
    """
    AST Visitor that walks test_flows_*.py files to extract FlowTest sequences.
    Handles variable tracing, `pytest.raises` isolation, and correctly processes
    `+=` loops without creating false self-edges.
    """

    def __init__(self, defining_module: str):
        self.defining_module = defining_module
        self.extracted_sequences: list[ExtractedFlowTestSequence] = []
        self.is_negative_assertion = False
        self.current_function = None
        self.current_test_name = ""

    def visit_With(self, node: ast.With):
        """
        Detects `with pytest.raises(...)` blocks.
        Sets a flag so any sequences extracted inside this block are marked as negative assertions.
        """
        is_pytest_raises = False
        for item in node.items:
            if isinstance(item.context_expr, ast.Call):
                func = item.context_expr.func
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    if func.value.id == "pytest" and func.attr == "raises":
                        is_pytest_raises = True

        previous_negative = self.is_negative_assertion
        if is_pytest_raises:
            self.is_negative_assertion = True

        self.generic_visit(node)

        self.is_negative_assertion = previous_negative

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """
        Tracks the current test function we are inside. This is used both for
        variable tracing and to attribute extracted sequences to their parent test.
        """
        previous_test_name = self.current_test_name
        if node.name.startswith("test_"):
            self.current_test_name = node.name

        previous_function = self.current_function
        self.current_function = node
        self.generic_visit(node)
        self.current_function = previous_function
        self.current_test_name = previous_test_name

    def visit_Call(self, node: ast.Call):
        func = node.func
        # Matches `self.run_sequence(...)` or `run_sequence(...)`
        is_run_sequence = False
        if isinstance(func, ast.Attribute) and func.attr == "run_sequence" or isinstance(func, ast.Name) and func.id == "run_sequence":
            is_run_sequence = True

        if is_run_sequence:
            sequence_arg = None
            if len(node.args) > 0:
                sequence_arg = node.args[0]
            else:
                for kw in node.keywords:
                    if kw.arg == "sequence":
                        sequence_arg = kw.value

            if sequence_arg:
                steps = self.resolve_sequence_argument(
                    sequence_arg, self.current_function
                )
                if steps:
                    self.extracted_sequences.append(
                        ExtractedFlowTestSequence(
                            steps=steps,
                            is_negative_assertion=self.is_negative_assertion,
                            defining_module=self.defining_module,
                            test_name=self.current_test_name,
                            line_number=node.lineno,
                        )
                    )

        self.generic_visit(node)

    def resolve_sequence_argument(
        self, node: ast.AST, enclosing_function: ast.FunctionDef
    ) -> list[ExtractedFlowStep]:
        """
        Resolves the `sequence` argument passed to `run_sequence()`.
        Can handle inline list literals or trace local variables.
        """
        if isinstance(node, ast.List):
            return self.parse_list_elements(node.elts)

        elif isinstance(node, ast.Name):
            target_var = node.id
            if enclosing_function:
                return self.scan_function_for_variable(target_var, enclosing_function)
        return []

    def scan_function_for_variable(
        self, var_name: str, function: ast.FunctionDef
    ) -> list[ExtractedFlowStep]:
        """
        Scans the enclosing function body for `var = [...]` and `var += [...]`.
        Because it parses in source order (using node.lineno) without unrolling loops,
        it avoids parsing repeated iterations of a loop.
        """
        assignments = []
        for node in ast.walk(function):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == var_name
                        and isinstance(node.value, ast.List)
                    ):
                        assignments.append(node)
            elif isinstance(node, ast.AugAssign):
                if (
                    isinstance(node.target, ast.Name)
                    and node.target.id == var_name
                    and isinstance(node.value, ast.List)
                ):
                    assignments.append(node)

        # Sort by line number to guarantee source order parsing for the variables
        assignments.sort(key=lambda n: n.lineno)

        steps = []
        for node in assignments:
            steps.extend(self.parse_list_elements(node.value.elts))
        return steps

    def parse_list_elements(self, elts: list[ast.AST]) -> list[ExtractedFlowStep]:
        steps = []
        for elt in elts:
            if isinstance(elt, ast.Call):
                func = elt.func
                if isinstance(func, ast.Name) and func.id == "FlowStep":
                    step = self.build_flow_test_step(elt)
                    if step:
                        steps.append(step)
        return steps

    def build_flow_test_step(self, node: ast.Call) -> ExtractedFlowStep:
        """
        Reduces a `FlowStep(...)` AST node down to its core fields.
        Extracts `expected_view` and determines if a back button or exception was expected.
        """
        expected_view = "UNRESOLVED_DYNAMIC_TARGET"
        is_back = False
        is_ex = False

        # arg 0 is expected_view
        if len(node.args) > 0:
            view_arg = node.args[0]
            if isinstance(view_arg, ast.Name):
                expected_view = view_arg.id
            elif isinstance(view_arg, ast.Attribute):
                expected_view = view_arg.attr

        # check kwargs for the other fields
        for kw in node.keywords:
            if kw.arg == "expected_view":
                if isinstance(kw.value, ast.Name):
                    expected_view = kw.value.id
                elif isinstance(kw.value, ast.Attribute):
                    expected_view = kw.value.attr

            if kw.arg in ["button_data_selection", "screen_return_value"]:
                if (
                    isinstance(kw.value, ast.Name)
                    and kw.value.id == "RET_CODE__BACK_BUTTON"
                ) or (
                    isinstance(kw.value, ast.Attribute)
                    and kw.value.attr == "RET_CODE__BACK_BUTTON"
                ):
                    is_back = True

            if kw.arg == "screen_return_value":
                if isinstance(kw.value, ast.Call):
                    if (
                        isinstance(kw.value.func, ast.Name)
                        and kw.value.func.id == "Exception"
                    ):
                        is_ex = True

        return ExtractedFlowStep(
            expected_view=expected_view,
            is_back_button_interaction=is_back,
            is_exception_interaction=is_ex,
        )

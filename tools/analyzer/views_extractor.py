import ast

from .models import Edge, ExtractedView


class ImportResolver(ast.NodeVisitor):
    """
    Walks the code's AST to build a map of all local class names to their
    fully qualified module paths (e.g. 'View' -> 'seedsigner.views.view.View').

    This allows us to accurately track where a View comes from, even if it
    was imported with an alias.
    """

    def __init__(self, current_file_path: str) -> None:
        self._import_map: dict[str, str] = {}

        parts = current_file_path.split("/")
        if parts[0] == "src":
            module_path = ".".join(parts[1:])
        else:
            module_path = ".".join(parts)

        module_path = module_path.removesuffix(".py")

        self.current_module = module_path
        if "." in module_path:
            self.current_package = module_path.rsplit(".", 1)[0]
        else:
            self.current_package = ""

    def visit_ClassDef(self, node: ast.ClassDef):
        # Register classes defined in this very file so they resolve properly
        if node.name.endswith("View"):
            self._import_map[node.name] = f"{self.current_module}.{node.name}"
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            local_name = alias.asname or alias.name
            self.import_map[local_name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.level > 0:
            base = self.current_package
            if node.module:
                base = f"{base}.{node.module}"
        else:
            base = str(node.module)

        for alias in node.names:
            local_name = alias.asname or alias.name
            if local_name == "*":
                continue
            full_path = f"{base}.{alias.name}"
            self.import_map[local_name] = full_path

        self.generic_visit(node)

    @property
    def import_map(self):
        return self._import_map


class ViewExtractor(ast.NodeVisitor):
    """
    Extracts all View classes defined in a module.

    It looks for any class that ends with 'View' (skipping the base View class itself).
    It captures the class name, module, and parent classes.
    """

    def __init__(self, current_module: str):
        self.current_module = current_module
        self.extracted_views: list[ExtractedView] = []

    def visit_ClassDef(self, node: ast.ClassDef):
        is_view = False
        base_classes = []

        if node.name.endswith("View"):
            is_view = True

        for base_class in node.bases:
            if isinstance(base_class, ast.Name):
                base_classes.append(base_class.id)
                if base_class.id.endswith("View"):
                    is_view = True
            elif isinstance(base_class, ast.Attribute):
                base_classes.append(base_class.attr)
                if base_class.attr.endswith("View"):
                    is_view = True

        if is_view and node.name not in ["View", "BackStackView"]:
            method_names: list[str] = []
            for class_member in node.body:
                if isinstance(class_member, ast.FunctionDef):
                    method_names.append(class_member.name)

            extracted_view = ExtractedView(
                view_class_name=node.name,
                defining_module=self.current_module,
                base_class_names=base_classes,
                method_names=method_names,
            )
            self.extracted_views.append(extracted_view)

        self.generic_visit(node)


class EdgeExtractor(ast.NodeVisitor):
    """
    Extracts all navigation routes (Edges) from a specific View.

    It looks for Destination objects and self.set_redirect() calls.
    It also tracks the specific conditions required to reach that route so that
    we know exactly under what conditions a user can navigate there.
    """

    def __init__(
        self,
        current_view: str,
        import_map: dict[str, str],
        current_module: str,
    ):
        self.current_view = current_view
        self._import_map = import_map
        self.current_module = current_module
        self.current_method: str = None

        self._condition_stack: list[str] = []
        self.is_back_button_disabled = False
        self.skip_current_view = False
        self.clear_history = False
        self._edges: list[Edge] = []

    @property
    def collected_edges(self) -> list[Edge]:
        """
        De-duplicates edges by (target_view, line_number).
        This fixes the double-counting of `set_redirect(Destination(...))`
        and handles variable re-assignments of the same Destination.
        """
        unique_edges = {}
        for edge in self._edges:
            key = (edge.target_view, edge.line_number)

            if key not in unique_edges:
                unique_edges[key] = edge
            else:
                # If we find a duplicate route on the same line, prefer the one that
                # was a redirect because `set_redirect()` forces `skip_current_view=True`.
                # This ensures we capture the most accurate state.
                if edge.is_redirect:
                    unique_edges[key] = edge

        return list(unique_edges.values())

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """
        Tracks the method we are currently analyzing. This ensures any Destination
        found inside this function is accurately attributed to it.

        We save and restore `self.current_method` to handle nested functions
        correctly (e.g., a helper function defined inside `run()`). When the AST
        visitor exits the inner function, it restores the outer function's name.
        """
        previous_method = self.current_method
        self.current_method = node.name

        self.generic_visit(node)

        self.current_method = previous_method

    def visit_If(self, node: ast.If):
        """
        Maintains a stack of logical conditions required to reach any given line
        of code. This allows us to accurately determine exactly what conditions
        must be met (e.g., which button was pressed) to trigger a Destination.

        We avoid using generic_visit because we must precisely control the stack:
        the condition must be active while traversing the 'if' body, and the
        negated condition must be active while traversing the 'else/elif' body.
        """

        # Extract the IF block's condition
        try:
            condition = ast.unparse(node.test)
        except Exception as e:
            condition = f"UNPARSE ERROR: {e}"

        # Normalize 'not' to 'NOT' in conditions (eg. if not x -> if NOT x)
        if condition.startswith("not "):
            condition = "NOT " + condition[4:]
        condition = condition.replace(" not ", " NOT ")
        condition = condition.replace("(not ", "(NOT ")

        self._condition_stack.append(condition)

        # Explore ONLY the IF block
        for child in node.body:
            self.visit(child)

        # remove the IF block's condition
        self._condition_stack.pop()

        # Check if there is an ELSE block
        if node.orelse:
            # Add the ELSE block's condition
            negated_condition = f"NOT ({condition})"

            # Simplify double negations, e.g. NOT (NOT seed_mnemonic) -> seed_mnemonic
            if negated_condition.startswith("NOT (NOT ") and negated_condition.endswith(
                ")"
            ):
                negated_condition = negated_condition[9:-1]

            self._condition_stack.append(negated_condition)

            # Explore ONLY the ELSE block
            for child in node.orelse:
                self.visit(child)

            # Remove all the added conditions after visiting the ELSE block
            self._condition_stack.pop()

    def visit_Call(self, node: ast.Call):
        # Trap Risk Logic: Check if the view manually disables the back button.
        # If the back button is hidden, the user has no way out of this screen
        # unless a forward route exists. We latch this boolean state on the class.
        for kwarg in node.keywords:
            if kwarg.arg == "show_back_button" and isinstance(
                kwarg.value, ast.Constant
            ):
                if kwarg.value.value is False:
                    self.is_back_button_disabled = True

        is_destination_call = self._is_destination_call(node)
        is_set_redirect_call = self._is_set_redirect_call(node)

        # Ignore any other method calls
        if not is_destination_call and not is_set_redirect_call:
            self.generic_visit(node)
            return

        # Extract the Destination Node
        if is_set_redirect_call:
            if not node.args:
                return
            destination_node = node.args[0]
        else:
            destination_node = node

        target_view = self._get_target_view(destination_node)
        metadata = self._extract_metadata(destination_node)

        current_conditions = " AND ".join(self._condition_stack)

        # A view is considered a 'trap risk' if the hardware back button is disabled
        # AND it doesn't instantly skip itself. If both are true, the user is stuck.
        skip_current_view = (
            True if is_set_redirect_call else metadata.get("skip_current_view", False)
        )
        is_trap_risk = self.is_back_button_disabled and not skip_current_view

        edge = Edge(
            source_view=self.current_view,
            target_view=target_view,
            condition=current_conditions,
            method=self.current_method or "unknown",
            line_number=node.lineno,
            source_file=self.current_module,
            is_redirect=is_set_redirect_call,
            skip_current_view=skip_current_view,
            clear_history=metadata.get("clear_history", False),
            is_trap_risk=is_trap_risk,
        )

        self._edges.append(edge)
        if not is_set_redirect_call:
            self.generic_visit(node)

    def _is_set_redirect_call(self, node: ast.Call) -> bool:
        """
        Checks if the AST node is a method call to `self.set_redirect(...)`.
        This is typically used in `__init__` or `__post_init__` to bypass `run()`.
        """
        return isinstance(node.func, ast.Attribute) and node.func.attr == "set_redirect"

    def _is_destination_call(self, node: ast.Call) -> bool:
        """
        Checks if the AST node is a direct constructor call to `Destination(...)`.
        This is typically returned from `run()` to navigate to the next screen.
        """
        return isinstance(node.func, ast.Name) and node.func.id == "Destination"

    def _extract_metadata(self, node: ast.Call) -> dict:
        """
        Extracts boolean configuration flags from a Destination call's keyword arguments.
        We ensure the value is an ast.Constant to prevent crashing on dynamic variables.
        """
        metadata = {
            "clear_history": False,
            "skip_current_view": False,
            "is_redirect": False,
        }

        if node.keywords:
            for kwarg in node.keywords:
                if kwarg.arg == "clear_history" and isinstance(
                    kwarg.value, ast.Constant
                ):
                    metadata["clear_history"] = kwarg.value.value
                elif kwarg.arg == "skip_current_view" and isinstance(
                    kwarg.value, ast.Constant
                ):
                    metadata["skip_current_view"] = kwarg.value.value

        return metadata

    # return Destination(ToolsAddressExplorerAddressListView, view_args=dict(is_change=button_data[selected_menu_num] == self.CHANGE))
    def _get_target_view(self, node: ast.Call) -> str:
        destination_view = ""

        # Case 1: The target view is directly passed as the first positional argument.
        # e.g. Destination(MainMenuView, ...)
        for arg in node.args:
            destination_view = ast.unparse(arg)
            if destination_view.endswith("View"):
                break

        # Case 2: The target view is passed explicitly as a keyword argument.
        # e.g. Destination(View_cls=MainMenuView, ...)
        if not destination_view:
            for kwarg in node.keywords:
                if kwarg.arg == "View_cls":
                    destination_view = ast.unparse(kwarg.value)
                    break

        if destination_view == "BackStackView":
            return "[BACK]"

        # If we never found anything, return unknown
        if not destination_view:
            return "UNKNOWN_VIEW"

        # Lookup the absolute module path from the import resolver we ran earlier.
        # If it's not in the map (e.g. it's defined in the same file), fallback to the short name.
        return self._import_map.get(destination_view, destination_view)

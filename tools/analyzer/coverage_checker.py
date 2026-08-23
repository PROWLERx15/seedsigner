from .models import Edge, ExtractedFlowTestSequence, ExtractedView


class CoverageAnalyzer:
    """
    Compares extracted FlowTest sequences against the static navigation graph
    to determine test coverage of the application's navigation edges.
    """

    def __init__(
        self,
        views: list[ExtractedView],
        edges: list[Edge],
        sequences: list[ExtractedFlowTestSequence],
        include_negative_assertions: bool = False,
    ):
        self.views = views
        self.edges = edges
        self.sequences = sequences
        self.include_negative_assertions = include_negative_assertions

        # Map view_class_name -> base_class_name
        # This allows us to map subclasses back to their parent classes if the
        # navigation edge was defined in the parent class.
        self.inheritance_map = {}
        for v in views:
            if v.base_class_names:
                base = v.base_class_names[0].split(".")[-1]
                self.inheritance_map[v.view_class_name] = base

        # Build set of static edges as (source, target)
        self.static_edges_set = set()
        self.static_back_sources = set()

        for e in edges:
            target = e.target_view.split(".")[-1]
            if target == "BackStackView":
                self.static_back_sources.add(e.source_view)
            else:
                self.static_edges_set.add((e.source_view, target))

    def resolve_source(self, source: str, target: str) -> str:
        """
        Walks up the inheritance tree to find the View that actually defined the transition.
        For example, if ScanSeedQRView inherits from ScanView, and the test uses ScanSeedQRView,
        we trace it back to ScanView to correctly credit the static edge.
        """
        current = source
        while current:
            if (current, target) in self.static_edges_set:
                return current
            if target == "BackStackView" and current in self.static_back_sources:
                return current
            current = self.inheritance_map.get(current)
        return source

    def reconcile(self) -> dict:
        """
        Reconciles the tested sequences against the static graph using rules 1-4.
        Returns a dictionary containing coverage statistics and lists of tested/untested edges.
        """
        covered_edges = set()
        unresolved_pairs = set()

        for seq in self.sequences:
            if seq.is_negative_assertion and not self.include_negative_assertions:
                continue

            steps = seq.steps
            for i in range(len(steps) - 1):
                src_step = steps[i]
                tgt_step = steps[i + 1]

                src = src_step.expected_view.split(".")[-1]
                tgt = tgt_step.expected_view.split(".")[-1]

                # Rule 3: Controller Exception
                # If a step explicitly expects an Exception, credit the edge to UnhandledExceptionView
                if src_step.is_exception_interaction:
                    if tgt == "UnhandledExceptionView":
                        covered_edges.add(
                            ("ControllerEventLoop", "UnhandledExceptionView")
                        )
                        continue

                # Rule 4: NotYetImplementedView
                # If the target is NotYetImplementedView and no direct transition exists,
                # credit it to the ControllerEventLoop as an implicit catch-all route.
                if tgt == "NotYetImplementedView":
                    resolved_src = self.resolve_source(src, tgt)
                    if (resolved_src, tgt) not in self.static_edges_set:
                        covered_edges.add(
                            ("ControllerEventLoop", "NotYetImplementedView")
                        )
                        continue

                # Rule 1: Direct Transition
                # Step N -> Step N+1 exists explicitly in the static graph.
                resolved_src = self.resolve_source(src, tgt)
                if (resolved_src, tgt) in self.static_edges_set:
                    covered_edges.add((resolved_src, tgt))
                    continue

                # Rule 2: Back Stack Pop
                # If this is not a direct transition, it might be a back-stack pop.
                # A pop is valid if the source view can return to the BackStackView,
                # AND the target view appeared at an earlier index in this exact sequence.
                resolved_back_src = self.resolve_source(src, "BackStackView")
                if resolved_back_src in self.static_back_sources:
                    appeared_earlier = False
                    for j in range(i):
                        if steps[j].expected_view.split(".")[-1] == tgt:
                            appeared_earlier = True
                            break
                    if appeared_earlier:
                        covered_edges.add((resolved_back_src, "BackStackView"))
                        continue

                # Unresolved pair: Test traversed an edge the static graph doesn't know about.
                unresolved_pairs.add((src, tgt))

        # Denominator Logic: Exclude UNRESOLVED_DYNAMIC_TARGET
        # We cannot expect tests to cover an edge whose destination we couldn't resolve statically.
        gate_relevant_edges = set()
        for e in self.edges:
            tgt = e.target_view.split(".")[-1]
            if tgt != "UNRESOLVED_DYNAMIC_TARGET":
                gate_relevant_edges.add((e.source_view, tgt))

        # Inject Controller dynamic edges into the denominator if they were tested
        if ("ControllerEventLoop", "UnhandledExceptionView") in covered_edges:
            gate_relevant_edges.add(("ControllerEventLoop", "UnhandledExceptionView"))
        if ("ControllerEventLoop", "NotYetImplementedView") in covered_edges:
            gate_relevant_edges.add(("ControllerEventLoop", "NotYetImplementedView"))

        # Filter covered_edges to only include gate_relevant_edges
        relevant_covered = covered_edges.intersection(gate_relevant_edges)

        tested_edges_count = len(relevant_covered)
        total_edges_count = len(gate_relevant_edges)
        percentage = (
            round((tested_edges_count / total_edges_count) * 100, 1) if total_edges_count > 0 else 0.0
        )

        return {
            "tested_edges_count": tested_edges_count,
            "total_edges_count": total_edges_count,
            "percentage": percentage,
            "unresolved_pairs_count": len(unresolved_pairs),
            "unresolved_pairs": list(unresolved_pairs),
            "covered_edges": list(relevant_covered),
            "untested_edges": list(gate_relevant_edges - relevant_covered),
        }

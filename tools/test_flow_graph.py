"""
Unit tests for tools/flow_graph.py.

Run from repo root:  pytest tools/test_flow_graph.py
"""
from pathlib import Path

from flow_graph import DEFAULT_TARGET, extract_from_file


def test_tools_menu_view_has_at_least_4_outbound_edges():
    """ToolsMenuView routes to at least 4 distinct destinations from its run() body."""
    views = extract_from_file(DEFAULT_TARGET)
    tools_menu = next((v for v in views if v.name == "ToolsMenuView"), None)
    assert tools_menu is not None, "ToolsMenuView not found in tools_views.py"

    distinct_targets = {edge.target_view for edge in tools_menu.edges}
    assert len(distinct_targets) >= 4, (
        f"Expected >=4 distinct outbound edges from ToolsMenuView, "
        f"got {len(distinct_targets)}: {sorted(distinct_targets)}"
    )


def test_extractor_finds_view_classes():
    """The extractor should find more than one View subclass in tools_views.py."""
    views = extract_from_file(DEFAULT_TARGET)
    assert len(views) > 1
    assert any(v.name == "ToolsMenuView" for v in views)


def test_default_target_exists():
    assert DEFAULT_TARGET.exists(), f"missing source file: {DEFAULT_TARGET}"
    assert DEFAULT_TARGET.suffix == ".py"

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from flow_test_extractor import reconcile
from navigation_graph import Edge


def edge(source, target):
    return Edge(
        source_view=source,
        target_view=target,
        condition="",
        method="run",
        line_number=1,
        source_file="test.py",
        is_redirect=False,
        skip_current_view=False,
        clear_history=False,
    )


def test_scan_subclass_flow_covers_scan_view_edge():
    report = reconcile(
        [edge("ScanView", "AddressVerificationStartView")],
        [("ScanAddressView", "AddressVerificationStartView", "test_scan", False)],
    )

    assert report.uncovered == []
    assert report.tested_only == []


def test_back_stack_flow_matches_static_back_edge():
    report = reconcile(
        [edge("SeedAddressVerificationView", "[BACK]")],
        [("SeedAddressVerificationView", "SeedSelectSeedView", "test_cancel", True)],
    )

    assert report.uncovered == []
    assert report.tested_only == []

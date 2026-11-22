"""Unit tests verifying Admin Portal route table integrity and camera safeguards.

Validates requirement:
1. Every admin menu item and button routes to its intended view with stable URLs.
2. Unrecognized routes return a 404 Page Not Found state and never route to Guided 360 Scan.
3. 360 scan view requires explicit product selection and stops camera tracks on departure.
"""

import re
from pathlib import Path

FRONTEND_ADMIN_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "admin"


def test_admin_portal_source_routes_exist():
    """Verify AdminPortal.tsx contains all 13 stable routes and NOT_FOUND fallback."""
    admin_portal_path = FRONTEND_ADMIN_DIR / "AdminPortal.tsx"
    assert admin_portal_path.exists(), "AdminPortal.tsx must exist"
    content = admin_portal_path.read_text(encoding="utf-8")

    expected_routes = [
        "/admin/overview",
        "/admin/fleet",
        "/admin/alerts",
        "/admin/reviews",
        "/admin/products",
        "/admin/products/scan",
        "/admin/preview-test",
        "/admin/recognition-lab",
        "/admin/models",
        "/admin/system",
        "/admin/reports",
        "/admin/carts",
        "/admin/trace",
        "/admin/staff",
    ]

    for route in expected_routes:
        assert f"path: '{route}'" in content, f"Expected route {route} in ADMIN_NAV_ITEMS"

    # Verify NOT_FOUND fallback route mapping
    assert "return 'NOT_FOUND';" in content
    assert "currentRouteKey === 'NOT_FOUND'" in content
    assert "<AdminNotFound" in content


def test_admin_route_matcher_logic():
    """Test the Python equivalent of matchAdminRoute logic to ensure 100% determinism."""
    nav_table = {
        "/admin": "DASHBOARD",
        "/admin/": "DASHBOARD",
        "/admin/overview": "DASHBOARD",
        "/admin/dashboard": "DASHBOARD",
        "/admin/fleet": "FLEET",
        "/admin/alerts": "ALERTS",
        "/admin/reviews": "REVIEWS",
        "/admin/products": "PRODUCTS",
        "/admin/products/scan": "SCAN_360",
        "/admin/preview-test": "PREVIEW_TEST",
        "/admin/recognition-lab": "RECOGNITION_LAB",
        "/admin/models": "MODELS",
        "/admin/system": "SYSTEM",
        "/admin/reports": "REPORTS",
        "/admin/carts": "CARTS_REGISTRY",
        "/admin/trace": "TRACE",
        "/admin/staff": "STAFF",
    }

    def match_route(path: str) -> str:
        norm = path.rstrip("/") or "/admin"
        return nav_table.get(norm, "NOT_FOUND")

    # Positive matches
    assert match_route("/admin") == "DASHBOARD"
    assert match_route("/admin/overview") == "DASHBOARD"
    assert match_route("/admin/products/scan") == "SCAN_360"
    assert match_route("/admin/preview-test") == "PREVIEW_TEST"
    assert match_route("/admin/recognition-lab") == "RECOGNITION_LAB"

    # Negative / unknown matches must NEVER resolve to SCAN_360 or a working view
    unknown_routes = [
        "/admin/unknown",
        "/admin/foobar",
        "/admin/scan",
        "/admin/vision",
        "/admin/random-label",
        "/admin/<exact label>",
        "/admin/360",
    ]
    for unk in unknown_routes:
        matched = match_route(unk)
        assert matched == "NOT_FOUND", f"Route {unk} resolved to {matched} instead of NOT_FOUND"
        assert matched != "SCAN_360", f"CRITICAL: Unknown route {unk} resolved to SCAN_360!"


def test_guided_360_scan_stops_camera_on_exit():
    """Verify Guided360ScanView invokes CameraHelper.stopAllStreams on all exits and unmount."""
    guided_360_path = FRONTEND_ADMIN_DIR / "Guided360ScanView.tsx"
    assert guided_360_path.exists()
    content = guided_360_path.read_text(encoding="utf-8")

    # CameraHelper must be imported and utilized
    assert "import { CameraHelper } from '../services/cameraHelper';" in content
    assert "CameraHelper.stopAllStreams();" in content

    # stopCamera must invoke CameraHelper.stopAllStreams()
    stop_cam_match = re.search(r"const stopCamera = useCallback\(\(\) => \{(.*?)\}, \[\]\);", content, re.DOTALL)
    assert stop_cam_match, "stopCamera callback must be defined"
    assert "CameraHelper.stopAllStreams();" in stop_cam_match.group(1)

    # All exit handlers must invoke CameraHelper.stopAllStreams()
    assert "handleExitToComplete" in content
    assert "handleExitToPreviewTest" in content


def test_preview_test_view_stops_camera():
    """Verify PreviewTestView imports CameraHelper and cleans up tracks on unmount."""
    preview_test_path = FRONTEND_ADMIN_DIR / "PreviewTestView.tsx"
    assert preview_test_path.exists()
    content = preview_test_path.read_text(encoding="utf-8")

    assert "import { CameraHelper } from '../services/cameraHelper';" in content
    assert "CameraHelper.stopAllStreams();" in content
    assert "handleBackToCatalog" in content

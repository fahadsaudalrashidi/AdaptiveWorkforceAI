"""Guard the unauthenticated synthetic demo from real-data functionality."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "executive-ui" / "src"


def test_public_demo_has_a_direct_route_and_sign_in_entry() -> None:
    app = (UI / "App.tsx").read_text()
    auth_gate = (UI / "auth" / "AuthGate.tsx").read_text()
    public_page = (UI / "public-demo" / "PublicDemoPage.tsx").read_text()

    assert "if (path === '/demo' || path.startsWith('/demo/'))" in app
    assert "return <PublicDemoPage />" in app
    assert "Explore the public synthetic-data demo" in auth_gate
    assert 'href="/demo"' in auth_gate
    assert "Scripted synthetic sample" in public_page
    assert "read-only" in public_page.lower()


def test_public_demo_does_not_call_real_data_or_upload_apis() -> None:
    public_page = (UI / "public-demo" / "PublicDemoPage.tsx").read_text()
    demo_mode = (UI / "pages" / "DemoMode.tsx").read_text()

    for source in (public_page, demo_mode):
        assert "/api/" not in source
        assert "fetch(" not in source
        assert "FileReader" not in source
        assert '<input type="file"' not in source
    assert "DEMO_COMPANIES" in demo_mode


def test_benchmark_panel_requires_explicit_verified_release_metadata() -> None:
    panel = (UI / "components" / "visualizations" / "BenchmarkGapPanel.tsx").read_text()

    assert "is_verified?: boolean" in panel
    assert "comparison.benchmark?.is_verified !== true" in panel
    assert "Illustrative data—not a real sector benchmark." in panel


def test_benchmark_governance_plan_defines_opt_in_privacy_and_retention() -> None:
    plan = (ROOT / "docs" / "BENCHMARK_CONTRIBUTION_GOVERNANCE.md").read_text()

    assert "starts disabled" in plan
    assert "five distinct opted-in tenants" in plan
    assert "ε=0.5, δ=10⁻⁶" in plan
    assert "withdraw" in plan.lower()
    assert "24 months" in plan
    assert "audit" in plan.lower()

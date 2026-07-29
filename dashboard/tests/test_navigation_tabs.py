from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]


def test_dashboard_navigation_is_grouped_into_route_aware_tabs() -> None:
    html = (PROJECT / "dashboard" / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (PROJECT / "dashboard" / "frontend" / "app.js").read_text(encoding="utf-8")

    for tab in ("work", "ai", "team", "market", "platform", "enterprise"):
        assert f'data-menu-tab="{tab}"' in html
        assert f'data-menu-panel="{tab}"' in html

    routes = (
        "/workbench",
        "/tasks",
        "/agents",
        "/skills",
        "/workspaces",
        "/marketplace",
        "/api-keys",
        "/security-center",
    )
    for route in routes:
        assert html.count(f'data-route="{route}"') == 1

    assert "function selectMenuTab" in script
    assert 'closest("[data-menu-panel]")' in script
    assert "sessionStorage.setItem" in script

from fastapi.testclient import TestClient

from zeb_cli import web_server


def test_dashboard_responses_include_browser_security_headers():
    previous_bound = getattr(web_server.app.state, "bound_host", None)
    previous_auth = getattr(web_server.app.state, "auth_required", None)
    web_server.app.state.bound_host = None
    web_server.app.state.auth_required = False
    try:
        response = TestClient(
            web_server.app,
            base_url="https://smartestmotherfuckerever.zeb.autos",
        ).get("/api/status")
    finally:
        web_server.app.state.bound_host = previous_bound
        web_server.app.state.auth_required = previous_auth

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")

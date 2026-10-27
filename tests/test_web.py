from fastapi.testclient import TestClient

from steward.web.app import _highlight, app


def test_highlight_escapes_user_text():
    out = str(_highlight("<script>alert(1)</script> crashes at level 3", "crashes at level 3"))
    assert "<script>" not in out and "&lt;script&gt;" in out and "<mark>crashes at level 3</mark>" in out


def test_pages_render_on_empty_db():
    c = TestClient(app)
    for path in ("/", "/inbox", "/board", "/queue", "/receipts"):
        r = c.get(path)
        assert r.status_code == 200, path
    assert "Dry run" in c.get("/").text

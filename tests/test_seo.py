"""SEO: metadatos por idioma, hreflang, JSON-LD, sitemap y robots."""

import json
import re

from starlette.testclient import TestClient

from app.main import app


def _ld(html: str) -> dict:
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert m, "falta JSON-LD"
    return json.loads(m.group(1))


def test_head_is_localized_with_hreflang_and_json_ld() -> None:
    client = TestClient(app)
    es = client.get("/?lang=es").text
    en = client.get("/?lang=en").text
    assert "<title>Apex Vox — Transcribe y resume tus reuniones con IA</title>" in es
    assert "<title>Apex Vox — Transcribe and summarize your meetings with AI</title>" in en
    assert 'property="og:locale" content="en_US"' in en
    for lang in ("es", "en", "x-default"):
        assert f'hreflang="{lang}"' in es
    assert "{{" not in es and "{{" not in en
    graph = {node["@type"]: node for node in _ld(en)["@graph"]}
    assert graph["SoftwareApplication"]["offers"][1]["priceCurrency"] == "USD"
    assert graph["Organization"]["logo"].endswith("/static/icons/icon-512.png")


def test_sitemap_and_robots() -> None:
    client = TestClient(app)
    sm = client.get("/sitemap.xml")
    assert sm.status_code == 200 and sm.headers["content-type"].startswith("application/xml")
    assert "?lang=en" in sm.text and "/legal/habeas-data" in sm.text and 'hreflang="es"' in sm.text
    robots = client.get("/robots.txt").text
    assert "Sitemap:" in robots and "Disallow: /api/" in robots and "Disallow: /mcp" in robots


def test_legal_pages_have_canonical_and_hreflang() -> None:
    html = TestClient(app).get("/legal/terminos?lang=en").text
    assert 'rel="canonical"' in html and 'hreflang="es"' in html and '<meta name="description"' in html

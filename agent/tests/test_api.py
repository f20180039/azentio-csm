from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _extract(path, schema="demo"):
    with open(path, "rb") as fh:
        return client.post("/v1/extract", data={"schema": schema}, files={"file": (path.name, fh, "application/pdf")})


def test_health_and_schemas():
    assert client.get("/health").json()["status"] == "ok"
    assert [s["key"] for s in client.get("/v1/schemas").json()] == ["demo"]


def test_extract_clean_sample(samples):
    body = _extract(samples / "clean_2.pdf").json()
    assert body["page_count"] == 1
    assert body["extraction_error"] is None
    assert body["fields"]["document_kind"] == "invoice"
    assert 184500.0 in [a["value"] for a in body["fields"]["amounts"]]
    assert body["security"]["injection"]["suspected"] is False
    masked = body["security"]["pii"]["masked"]
    assert masked["PAN"] == 1 and masked["PHONE"] == 1 and masked["ACCOUNT"] == 1
    assert "[PAN]" in body["pages"][0]["text"]
    assert body["model"] == {"provider": "mock", "name": "mock", "prompt_version": "extract-v1"}


def test_extract_redteam_sample(samples):
    body = _extract(samples / "redteam_hidden_text.pdf").json()
    sec = body["security"]
    assert sec["hidden_text"][0]["reason"] == "white_text"
    assert sec["injection"]["suspected"] is True
    assert "Ignore previous" not in body["pages"][0]["text"]


def test_rejects_unknown_schema_and_non_pdf(samples, tmp_path):
    assert _extract(samples / "clean_1.pdf", schema="nope").status_code == 422
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"hello")
    assert _extract(junk).status_code == 422


def test_rejects_too_many_pages(tmp_path):
    import fitz

    doc = fitz.open()
    for _ in range(51):
        doc.new_page()
    path = tmp_path / "long.pdf"
    doc.save(path)
    resp = _extract(path)
    assert resp.status_code == 422 and "limit is 50" in resp.json()["detail"]


def test_explain_endpoint_with_mock():
    body = client.post("/v1/explain", json={
        "case_type": "demo",
        "findings": [{"id": "f1", "rule_id": "DEMO-LARGE-AMOUNT", "title": "Large amount",
                      "detail": "Above 1 lakh", "evidence": [{"page": 1, "quote": "Rs. 1,84,500.00"}]}],
        "pages": [{"document_id": "d1", "page": 1, "text": "Total payable: Rs. 1,84,500.00"}],
    }).json()
    assert body["notes"][0]["quotes"][0]["text"] == "Rs. 1,84,500.00"
    assert body["dropped"] == []

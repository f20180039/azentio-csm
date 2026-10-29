from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from . import logs
from .config import settings
from .explain import ExplainRequest, explain
from .extract import extract
from .llm.gateway import ProviderError, build_gateway
from .pdf import PdfError
from .schemas import REGISTRY, get

logs.setup()
app = FastAPI(title="Case Intelligence Agent", version="0.1.0")
gateway = build_gateway(settings)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_chain": gateway.chain, "schemas": sorted(REGISTRY)}


@app.get("/v1/schemas")
def schemas() -> list[dict]:
    return [
        {"key": s.key, "prompt_version": s.prompt_version, "json_schema": s.model.model_json_schema()}
        for s in REGISTRY.values()
    ]


@app.post("/v1/extract")
def extract_endpoint(file: UploadFile = File(...), schema: str = Form(...)) -> dict:
    spec = get(schema)
    if spec is None:
        raise HTTPException(422, f"unknown schema '{schema}'; known: {sorted(REGISTRY)}")
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"file exceeds {settings.max_upload_bytes // (1024 * 1024)} MB")
    try:
        return extract(data, spec, gateway, settings)
    except PdfError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/v1/explain")
def explain_endpoint(req: ExplainRequest) -> dict:
    try:
        return explain(req, gateway)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc

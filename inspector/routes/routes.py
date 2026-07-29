import base64
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Form
from starlette.concurrency import run_in_threadpool

from common.config import SETTINGS
from inspector.model import BaseInspector, InspectorRegistry
from inspector.routes.dependency import get_registry
from inspector.schemas.prediction import (
    HealthResponse, ModelInfo, PredictionResponse, ThresholdRequest, ThresholdResponse
)

router = APIRouter()


def _select(registry: InspectorRegistry, ai_model: str) -> BaseInspector:
    try:
        return registry.get(ai_model)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown ai_model '{ai_model}'. Available: {registry.names}",
        )


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(registry: InspectorRegistry = Depends(get_registry)):
    return HealthResponse(
        status="ok", device=SETTINGS.device, devices=registry.get_devices()
    )


@router.get("/models", response_model=list[ModelInfo], tags=["system"])
def models(registry: InspectorRegistry = Depends(get_registry)):
    return registry.get_models_info()


@router.get("/threshold", response_model=ThresholdResponse, tags=["threshold"])
def get_threshold(
        ai_model: str,
        registry: InspectorRegistry = Depends(get_registry),
):
    inspector = _select(registry, ai_model)
    value = inspector.get_threshold()
    if isinstance(value, dict):
        return ThresholdResponse(ai_model=inspector.name, thresholds=value)
    return ThresholdResponse(ai_model=inspector.name, threshold=value)


@router.put("/threshold", response_model=ThresholdResponse, tags=["threshold"])
def set_threshold(
        body: ThresholdRequest,
        registry: InspectorRegistry = Depends(get_registry),
):
    inspector = _select(registry, body.ai_model)
    try:
        inspector.set_threshold(body.threshold, body.class_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    value = inspector.get_threshold()
    if isinstance(value, dict):
        return ThresholdResponse(ai_model=inspector.name, thresholds=value)
    return ThresholdResponse(ai_model=inspector.name, threshold=value)


@router.post("/embeddings", response_model=PredictionResponse, tags=["inference"])
async def get_embeddings(
        ai_model: str = Form(...),
        file: UploadFile = File(...),
        registry: InspectorRegistry = Depends(get_registry),
):
    inspector = _select(registry, ai_model)

    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image.")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        # Inference is synchronous and GPU-bound (vaium also holds a global lock),
        # so keep it off the event loop or it stalls every other request.
        return await run_in_threadpool(inspector.predict, image_bytes)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Inference failed: {exc}") from exc


@router.post("/decode", response_model=str, tags=["inference"])
async def decode(
        file: UploadFile = File(...)
):
    try:
        raw_bytes = await file.read()
        b64_string = base64.b64encode(raw_bytes).decode("utf-8")
        return b64_string
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Decode failed: {exc}") from exc

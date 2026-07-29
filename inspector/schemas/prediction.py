from pydantic import BaseModel, Field


class Stage(BaseModel):
    """One epoxy classification stage (routing classifier, then type model)."""
    inference_model: str
    version: str | None
    decision: str
    confidence: float
    feature_vector: list[float]


class Box(BaseModel):
    """One vaium detection that passed its per-class threshold."""
    decision: str
    confidence: float
    box_embedding: list[float] | None = None
    threshold: float | None = None


class PredictionResponse(BaseModel):
    """Superset response shared by every inspector.

    The core fields are always present; `stages` is epoxy-only and `boxes` is
    vaium-only, so a consumer that just reads decision/confidence/feature_vector
    does not have to branch on `ai_model`.
    """

    # --- common core ---
    ai_model: str
    version: str | None = None
    classes: list[str]
    decision: str
    # vaium returns None when no box survives thresholding...
    confidence: float | None = None
    # ...and when an image is rejected as yellow/dark before the network runs.
    feature_vector: list[float] | None = None
    elapsed_time: float

    # --- epoxy only ---
    inference_model: str | None = None
    threshold: float | None = None
    stages: list[Stage] | None = None

    # --- vaium only ---
    boxes: list[Box] | None = None


class ModelInfo(BaseModel):
    ai_model: str
    model_name: str
    version: str | None = None


class ThresholdResponse(BaseModel):
    ai_model: str
    # Single image-level threshold (epoxy), or the per-class map (vaium).
    threshold: float | None = None
    thresholds: dict[str, float] | None = None


class ThresholdRequest(BaseModel):
    ai_model: str
    threshold: float = Field(..., ge=0.0, le=100.0)
    # Required by per-class models such as vaium; ignored by epoxy.
    class_name: str | None = None


class HealthResponse(BaseModel):
    status: str
    device: str
    devices: dict[str, str]

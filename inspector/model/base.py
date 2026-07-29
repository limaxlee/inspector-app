from abc import ABC, abstractmethod


class BaseInspector(ABC):
    """Common surface every inspector model exposes to the routes layer.

    `name` doubles as the registry key and as the `ai_model` value reported in
    prediction responses, so a request and its response always agree.
    """

    name: str = ""
    version: str | None = None

    def __init__(self):
        self.device = None

    @abstractmethod
    def load(self) -> None:
        """Load weights and run one warmup pass. Called once at startup."""

    @abstractmethod
    def predict(self, image_bytes: bytes) -> dict:
        """Run inference on raw image bytes and return a PredictionResponse dict."""

    def get_models_info(self) -> list[dict]:
        return [{"ai_model": self.name, "model_name": self.name, "version": self.version}]

    def get_threshold(self, key: str | None = None):
        """Return one threshold when `key` is given, or all of them when it is not."""
        raise NotImplementedError

    def set_threshold(self, value: float, key: str | None = None) -> None:
        raise NotImplementedError

    def release(self) -> None:
        pass

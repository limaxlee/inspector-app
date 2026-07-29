from inspector.model.base import BaseInspector


def _build_epoxy() -> BaseInspector:
    from inspector.model.epoxy import EpoxyInspector
    return EpoxyInspector()


def _build_vaium() -> BaseInspector:
    # Imported lazily: this pulls in the vendored `chip_detector` package, which
    # an epoxy-only deployment does not have to ship.
    from inspector.model.vaium import VaiumDetector
    return VaiumDetector()


_BUILDERS = {
    "epoxy": _build_epoxy,
    "vaium": _build_vaium,
}


class InspectorRegistry:
    """Holds one loaded inspector per enabled model, keyed by `ai_model`."""

    def __init__(self, names: list[str]):
        requested = [n.strip().lower() for n in names if n and n.strip()]
        if not requested:
            raise ValueError("No models enabled. Set `models` in config.yaml.")

        unknown = [n for n in requested if n not in _BUILDERS]
        if unknown:
            raise ValueError(
                f"Unknown models in config: {unknown}. Available: {sorted(_BUILDERS)}"
            )

        # dict.fromkeys de-duplicates while preserving the configured order.
        self._requested = list(dict.fromkeys(requested))
        self._inspectors: dict[str, BaseInspector] = {}

    def load(self) -> None:
        for name in self._requested:
            inspector = _BUILDERS[name]()
            inspector.load()
            self._inspectors[name] = inspector

    def get(self, ai_model: str) -> BaseInspector:
        key = (ai_model or "").strip().lower()
        if key not in self._inspectors:
            raise KeyError(key)
        return self._inspectors[key]

    @property
    def names(self) -> list[str]:
        return list(self._inspectors)

    def __iter__(self):
        return iter(self._inspectors.values())

    def get_models_info(self) -> list[dict]:
        return [info for inspector in self for info in inspector.get_models_info()]

    def get_devices(self) -> dict[str, str]:
        return {name: str(i.device) for name, i in self._inspectors.items()}

    def release(self) -> None:
        for inspector in self._inspectors.values():
            inspector.release()
        self._inspectors.clear()

from fastapi import Request

from inspector.model import InspectorRegistry


def get_registry(request: Request) -> InspectorRegistry:
    """Return the singleton registry loaded at startup (see inspector.__main__)."""
    return request.app.state.inspectors

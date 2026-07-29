import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from inspector.routes import router
from common.config import SETTINGS
from inspector.model import InspectorRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load every enabled model's checkpoints once at startup (with a warmup pass).
    registry = InspectorRegistry(SETTINGS.models)
    registry.load()
    app.state.inspectors = registry
    try:
        yield
    finally:
        registry.release()


app = FastAPI(title="Inspector Service", lifespan=lifespan)
app.include_router(router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=SETTINGS.server_port)

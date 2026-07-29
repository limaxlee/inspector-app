import os
import yaml
import argparse
from pydantic_settings import BaseSettings

from common.constants import ROOT_DIR

def _csv(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


_ENV_MAP = {
    "server_port": ("SERVER_PORT", int),
    "checkpoint_dir": ("CHECKPOINT_DIR", str),
    "threshold": ("THRESHOLD", float),
    "device": ("DEVICE", str),
    "models": ("MODELS", _csv),
}

_REQUIRED_KEYS = ("server_port", "checkpoint_dir", "threshold", "device", "models")


def load_config() -> dict:
    default_config = os.path.join(ROOT_DIR, "config.yaml")
    parser = argparse.ArgumentParser(description="Inspector Service Configurations")
    parser.add_argument("--config", "-c", type=str, help="Path to the config.yaml", default=default_config)
    args, _ = parser.parse_known_args()

    config = {}
    if os.path.isfile(args.config):
        with open(args.config, "r") as f:
            config.update(yaml.safe_load(f))

    for key, (env_name, caster) in _ENV_MAP.items():
        env_value = os.getenv(env_name)
        if env_value is not None:
            config[key] = caster(env_value)

    missing_config = [key for key in _REQUIRED_KEYS if key not in config or config[key] in (None, "")]
    if missing_config:
        raise ValueError(f"Missing required configuration: {missing_config}")

    return config


class Settings(BaseSettings, extra="allow"):
    server_port: int
    checkpoint_dir: str = "checkpoint"
    threshold: float = 99.0
    device: str = "auto"
    # Which inspectors to build and load at startup; also the valid `ai_model` values.
    models: list[str] = ["epoxy"]


SETTINGS = Settings(**load_config())

"""
tools/config_loader.py
Loads config.yaml and .env. All agents import this.
"""
import yaml
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")


class _Models:
    """Attribute-style access to the models block in config.yaml."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def __getattr__(self, name: str) -> str:
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(
                f"Model key '{name}' not found in config.yaml.\n"
                f"  Available keys in your models block: {list(self._data.keys())}\n"
                f"  The models block was expanded in a recent update — 8 keys are now required.\n"
                f"  Fix: copy config.example.yaml to config.yaml and re-fill your user_profile section,\n"
                f"  OR manually add the missing keys from config.example.yaml to your existing config.yaml."
            )


class _Config(dict):
    """dict subclass that also exposes cfg.models for attribute-style access."""

    @property
    def models(self) -> _Models:
        return _Models(self.get("models") or {})


def _load_config() -> _Config:
    with open(ROOT / "config.yaml") as f:
        return _Config(yaml.safe_load(f))


cfg = _load_config()

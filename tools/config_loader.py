"""
tools/config_loader.py
Loads config.yaml and .env. All agents import this.
"""
import yaml
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)

cfg = load_config()

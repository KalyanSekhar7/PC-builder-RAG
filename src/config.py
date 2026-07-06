"""Application configuration — externalized settings."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Model
MODEL_NAME = os.getenv("MODEL_NAME", "claude-sonnet-4-5-20250929")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "4096"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.3"))

# Agent
MAX_AGENT_TURNS = int(os.getenv("MAX_AGENT_TURNS", "30"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# Data
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "agent.log")

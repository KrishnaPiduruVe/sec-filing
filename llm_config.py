"""Shared, environment-driven LangChain chat-model configuration."""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model


def get_chat_model():
    """Initialize the model selected by PRIMARY_MODEL in the project .env."""
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    prefix = os.getenv("PRIMARY_MODEL", "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", prefix):
        raise ValueError(
            "Set PRIMARY_MODEL in .env to a provider prefix such as GOOGLE or OPENAI."
        )

    provider = os.getenv(f"{prefix}_MODEL_PROVIDER", "").strip()
    model_name = os.getenv(f"{prefix}_MODEL_NAME", "").strip()
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    missing = [
        variable
        for variable, value in (
            (f"{prefix}_MODEL_PROVIDER", provider),
            (f"{prefix}_MODEL_NAME", model_name),
            (f"{prefix}_API_KEY", api_key),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Missing model configuration in .env: {', '.join(missing)}")
    return init_chat_model(
        model_name,
        model_provider=provider,
        api_key=api_key,
    )

"""Shared, environment-driven LangChain chat-model configuration."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings


def _load_config() -> None:
    load_dotenv(Path(__file__).with_name(".env"), override=False)


def _primary_model_prefix() -> str:
    prefix = os.getenv("PRIMARY_MODEL", "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", prefix):
        raise ValueError(
            "Set PRIMARY_MODEL in .env to a provider prefix such as GOOGLE or OPENAI."
        )
    return prefix


def get_chat_model():
    """Initialize the model selected by PRIMARY_MODEL in the project .env."""
    _load_config()
    prefix = _primary_model_prefix()

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


def get_model_identifier() -> str:
    """Return a non-secret identifier for the configured chat model."""
    _load_config()
    prefix = _primary_model_prefix()
    model_name = os.getenv(f"{prefix}_MODEL_NAME", "").strip()
    if not model_name:
        raise ValueError(f"Missing model configuration in .env: {prefix}_MODEL_NAME")
    return model_name


def get_embedding_settings() -> tuple[str, str, str]:
    """Return embedding provider, model, and API key from the project .env."""
    _load_config()
    provider = os.getenv("EMBEDDING_PROVIDER", "").strip()
    model_name = os.getenv("EMBEDDING_MODEL", "").strip()
    if not provider or not model_name:
        missing = [
            variable
            for variable, value in (
                ("EMBEDDING_PROVIDER", provider),
                ("EMBEDDING_MODEL", model_name),
            )
            if not value
        ]
        raise ValueError(f"Missing embedding configuration in .env: {', '.join(missing)}")

    api_key = os.getenv("EMBEDDING_API_KEY", "").strip()
    if not api_key:
        api_key = os.getenv(f"{provider.upper()}_API_KEY", "").strip()
    if not api_key:
        prefix = _primary_model_prefix()
        chat_provider = os.getenv(f"{prefix}_MODEL_PROVIDER", "").strip()
        if provider == chat_provider:
            api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    return provider, model_name, api_key


def get_embedding_model_identifier() -> str:
    """Return a non-secret provider/model identifier for embedding usage records."""
    provider, model_name, _ = get_embedding_settings()
    return f"{provider}:{model_name}"


def get_embedding_model():
    """Initialize the embedding integration selected in the project .env.

    Provider-specific options can be supplied as a JSON object in
    ``EMBEDDING_OPTIONS``. Most providers use LangChain's generic factory;
    Google GenAI uses its LangChain integration because it is not registered
    with that factory.
    """
    provider, model_name, api_key = get_embedding_settings()
    raw_options = os.getenv("EMBEDDING_OPTIONS", "").strip()
    options: dict[str, Any] = {}
    if raw_options:
        try:
            parsed_options = json.loads(raw_options)
        except json.JSONDecodeError as exc:
            raise ValueError("EMBEDDING_OPTIONS must contain a JSON object.") from exc
        if not isinstance(parsed_options, dict):
            raise ValueError("EMBEDDING_OPTIONS must contain a JSON object.")
        options = parsed_options
    if "api_key" in options:
        raise ValueError("Set embedding credentials with EMBEDDING_API_KEY, not EMBEDDING_OPTIONS.")
    if provider == "google_genai":
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
        except ImportError as exc:
            raise RuntimeError(
                "Install the Google GenAI integration: pip install -e '.[google]'"
            ) from exc
        if api_key:
            options["api_key"] = api_key
        return GoogleGenerativeAIEmbeddings(model=model_name, **options)
    if api_key:
        options["api_key"] = api_key
    return init_embeddings(model_name, provider=provider, **options)

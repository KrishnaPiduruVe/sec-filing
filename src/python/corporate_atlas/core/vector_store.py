"""Create and access the persistent Chroma filing vector store."""

from __future__ import annotations

from pathlib import Path
from corporate_atlas.paths import DATA_ROOT
from corporate_atlas.settings import SETTINGS

from corporate_atlas.core.llm_config import get_embedding_model, get_embedding_settings

DEFAULT_VECTOR_ROOT = DATA_ROOT / SETTINGS.paths.vector_dir
COLLECTION_NAME = SETTINGS.paths.vector_collection


def embedding_settings() -> tuple[str, str, str]:
    """Return the configured embedding provider, model, and API key."""
    return get_embedding_settings()


def get_embeddings():
    """Initialize embeddings using the provider selected in the project .env."""
    try:
        return get_embedding_model()
    except ImportError as exc:
        provider, _, _ = embedding_settings()
        raise RuntimeError(
            f"Install the LangChain integration for embedding provider {provider!r}."
        ) from exc


def open_vector_store(
    persist_directory: Path = DEFAULT_VECTOR_ROOT,
    *,
    create: bool = False,
):
    """Open the persistent Chroma collection, optionally creating its directory."""
    if not create and not persist_directory.is_dir():
        raise FileNotFoundError(
            f"Vector database not found: {persist_directory}. "
            "Build it first with corporate_atlas.core.build_vector_store."
        )
    try:
        from langchain_chroma import Chroma
    except ImportError as exc:
        raise RuntimeError(
            "Install the vector extra: pip install -e '.[vector]'"
        ) from exc
    if create:
        persist_directory.mkdir(parents=True, exist_ok=True)
    store = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=str(persist_directory),
    )
    if not create and not store.get().get("ids"):
        raise ValueError(
            f"Vector database is empty: {persist_directory}. "
            "Build it first with corporate_atlas.core.build_vector_store."
        )
    return store

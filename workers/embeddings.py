"""Article embedding generation, backed by fastembed (ONNX runtime,
CPU-only — no torch/GPU dependency). The model is loaded once at import
time, mirroring how entity_extractor.py loads the spaCy model once.
"""

import os
import tomllib
from pathlib import Path

from fastembed import TextEmbedding

from vector_store import EMBEDDING_DIMENSIONS


DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "clustering.toml"
)

CONFIG_PATH = Path(
    os.getenv(
        "CLUSTERING_CONFIG_PATH",
        str(DEFAULT_CONFIG_PATH),
    )
)


def _load_model_name() -> str:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Clustering configuration does not exist: {CONFIG_PATH}"
        )

    with CONFIG_PATH.open("rb") as handle:
        config = tomllib.load(handle)

    return config.get("embeddings", {}).get(
        "model_name",
        "BAAI/bge-small-en-v1.5",
    )


MODEL_NAME = _load_model_name()

_model = TextEmbedding(model_name=MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    vectors = [vector.tolist() for vector in _model.embed(texts)]

    for vector in vectors:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise RuntimeError(
                f"Embedding model {MODEL_NAME!r} produced "
                f"{len(vector)}-dim vectors; expected {EMBEDDING_DIMENSIONS}"
            )

    return vectors

import uuid
import contextlib
import io
import logging
import chromadb

from crewai.utilities.paths import db_storage_path
from typing import Optional, List
from typing import Dict, Any
from crewai.utilities import EmbeddingConfigurator
from crewai.knowledge.storage.base_knowledge_storage import BaseKnowledgeStorage


@contextlib.contextmanager
def suppress_logging(
    logger_name="chromadb.segment.impl.vector.local_persistent_hnsw",
    level=logging.ERROR,
):
    logger = logging.getLogger(logger_name)
    original_level = logger.getEffectiveLevel()
    logger.setLevel(level)
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
        contextlib.suppress(UserWarning),
    ):
        yield
    logger.setLevel(original_level)


class KnowledgeStorage(BaseKnowledgeStorage):
    """
    Extends Storage to handle embeddings for memory entries, improving
    search efficiency.
    """

    collection: Optional[chromadb.Collection] = None

    def __init__(self, embedder_config=None):
        self._initialize_app(embedder_config or {})

    def search(
        self,
        query: List[str],
        limit: int = 3,
        filter: Optional[dict] = None,
        score_threshold: float = 0.35,
    ) -> List[Dict[str, Any]]:
        with suppress_logging():
            if self.collection:
                fetched = self.collection.query(
                    query_texts=query,
                    n_results=limit,
                    where=filter,
                )
                results = []
                for i in range(len(fetched["ids"][0])):
                    result = {
                        "id": fetched["ids"][0][i],
                        "metadata": fetched["metadatas"][0][i],
                        "context": fetched["documents"][0][i],
                        "score": fetched["distances"][0][i],
                    }
                    if result["score"] >= score_threshold:
                        results.append(result)
                return results
            else:
                raise Exception("Collection not initialized")

    def _initialize_app(self, embedder_config: Optional[Dict[str, Any]] = None):
        import chromadb
        from chromadb.config import Settings

        self._set_embedder_config(embedder_config)

        chroma_client = chromadb.PersistentClient(
            path=f"{db_storage_path()}/knowledge",
            settings=Settings(allow_reset=True),
        )

        self.app = chroma_client

        try:
            self.collection = self.app.get_or_create_collection(name="knowledge")
        except Exception:
            raise Exception("Failed to create or get collection")

    def reset(self):
        if self.app:
            self.app.reset()

    def save(
        self, documents: List[str], metadata: Dict[str, Any] | List[Dict[str, Any]]
    ):
        if self.collection:
            metadatas = [metadata] if isinstance(metadata, dict) else metadata

            self.collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=[str(uuid.uuid4()) for _ in range(len(documents))],
            )
        else:
            raise Exception("Collection not initialized")

    def _create_default_embedding_function(self):
        from crewai.knowledge.embedder.fastembed import FastEmbed

        return FastEmbed().embed_texts

    def _set_embedder_config(
        self, embedder_config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Set the embedding configuration for the knowledge storage.

        Args:
            embedder_config (Optional[Dict[str, Any]]): Configuration dictionary for the embedder.
                If None or empty, defaults to the default embedding function.
        """
        self.embedder_config = (
            EmbeddingConfigurator().configure_embedder(embedder_config)
            if embedder_config
            else self._create_default_embedding_function()
        )
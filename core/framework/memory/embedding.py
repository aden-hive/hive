"""
Embedding Provider Interface and Implementations.

Provides embedding generation for semantic similarity search.
"""

from abc import ABC, abstractmethod
from typing import Any


class EmbeddingProvider(ABC):
    """
    Abstract base class for embedding providers.

    Embedding providers convert text into vector representations
    that can be used for semantic similarity search.
    """

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """
        Generate an embedding for a single text.

        Args:
            text: The text to embed

        Returns:
            A list of floats representing the embedding vector
        """
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        """
        Return the dimension of the embedding vectors.

        Returns:
            The number of dimensions in the embedding vectors
        """
        pass


class MockEmbeddingProvider(EmbeddingProvider):
    """
    Mock embedding provider for testing.

    Generates deterministic embeddings based on text content.
    Not suitable for production use.
    """

    def __init__(self, dimension: int = 384):
        self._dimension = dimension

    async def embed(self, text: str) -> list[float]:
        """Generate a deterministic mock embedding based on text hash."""
        import hashlib

        text_hash = hashlib.sha256(text.encode()).hexdigest()
        embedding = []
        for i in range(self._dimension):
            chunk = text_hash[i % len(text_hash) : (i % len(text_hash)) + 8]
            if len(chunk) < 8:
                chunk = chunk + text_hash[: 8 - len(chunk)]
            value = int(chunk, 16) / (16**8) * 2 - 1
            embedding.append(value)

        norm = sum(x * x for x in embedding) ** 0.5
        if norm > 0:
            embedding = [x / norm for x in embedding]

        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate mock embeddings for multiple texts."""
        return [await self.embed(text) for text in texts]

    def get_dimension(self) -> int:
        return self._dimension


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI embedding provider using the OpenAI API.

    Requires the OPENAI_API_KEY environment variable to be set.
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        dimension: int | None = None,
    ):
        """
        Initialize the OpenAI embedding provider.

        Args:
            model: The OpenAI embedding model to use
            api_key: OpenAI API key (if None, reads from OPENAI_API_KEY env var)
            dimension: Output dimension (only for models that support it)
        """
        self._model = model
        self._api_key = api_key
        self._dimension = dimension or self._get_default_dimension(model)
        self._client: Any = None

    def _get_default_dimension(self, model: str) -> int:
        """Get the default dimension for a model."""
        dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        return dimensions.get(model, 1536)

    def _get_client(self) -> Any:
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            try:
                import openai

                self._client = openai.AsyncOpenAI(api_key=self._api_key)
            except ImportError as e:
                raise ImportError(
                    "openai package is required for OpenAIEmbeddingProvider. "
                    "Install it with: pip install openai"
                ) from e
        return self._client

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding using OpenAI API."""
        client = self._get_client()
        kwargs: dict[str, Any] = {"input": text, "model": self._model}
        if self._dimension and "text-embedding-3" in self._model:
            kwargs["dimensions"] = self._dimension

        response = await client.embeddings.create(**kwargs)
        return list(response.data[0].embedding)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts using OpenAI API."""
        client = self._get_client()
        kwargs: dict[str, Any] = {"input": texts, "model": self._model}
        if self._dimension and "text-embedding-3" in self._model:
            kwargs["dimensions"] = self._dimension

        response = await client.embeddings.create(**kwargs)
        return [list(item.embedding) for item in response.data]

    def get_dimension(self) -> int:
        return self._dimension

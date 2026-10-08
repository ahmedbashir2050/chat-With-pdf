"""Infrastructure adapters for the LLM/embedding domain interfaces,
backed by OpenAI. Behavior is unchanged from the original
embedding_utils.py — this is a structural move (functions → classes
implementing domain.interfaces.EmbeddingService / LLMService), not a
rewrite of what they do.
"""

import base64

from openai import OpenAI

from ..config import Settings


class OpenAIEmbeddingService:
    """Implements domain.interfaces.EmbeddingService."""

    def __init__(self, client: OpenAI, model: str):
        self._client = client
        self._model = model

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._model, input=texts)
        items = sorted(response.data, key=lambda d: d.index)
        return [item.embedding for item in items]

    def embed_one(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]


class OpenAILLMService:
    """Implements domain.interfaces.LLMService."""

    def __init__(self, client: OpenAI, model: str):
        self._client = client
        self._model = model

    def complete(self, messages: list[dict], temperature: float = 0) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content

    def complete_vision(self, prompt: str, image_png_bytes: bytes) -> str:
        """Used by the OCR fallback (parsing/ocr_service.py) to transcribe
        a rasterized page image via a vision-capable chat model."""
        img_b64 = base64.b64encode(image_png_bytes).decode()
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    ],
                }
            ],
            temperature=0,
        )
        return (response.choices[0].message.content or "").strip()


def build_openai_client(settings: Settings) -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)

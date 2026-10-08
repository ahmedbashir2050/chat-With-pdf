"""Composition root. This is the one place that knows about every
concrete implementation — routers depend on these provider functions via
FastAPI's `Depends()`, never on infrastructure classes directly. Swapping
an implementation (e.g. a different LLM provider) means changing exactly
one function here.

Stateless adapters (OpenAI client, embedding/LLM/OCR/parser/vector-store
services) are built once as module-level singletons — they hold no
per-request state. Repositories and application services are built fresh
per request since they wrap a request-scoped SQLAlchemy Session.
"""

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..application.answer_generator_service import AnswerGeneratorService
from ..application.auth_service import AuthService
from ..application.chat_service import ChatService
from ..application.citation_validator_service import CitationValidatorService
from ..application.claim_verification_service import ClaimVerificationService
from ..application.qa_service import QAService
from ..application.summarization_service import SummarizationService
from ..config import settings
from ..context.context_manager import ContextManagerService
from ..database import get_db
from ..llm.openai_services import OpenAIEmbeddingService, OpenAILLMService, build_openai_client
from ..longcontext.cache import LongContextCache
from ..longcontext.long_context_analyzer import LongContextAnalyzer
from ..longcontext.map_reduce_summarizer import LongContextSummarizer
from ..longcontext.study_guide_generator import StudyGuideGenerator
from ..parsing.document_parser_v2 import DocumentIntelligenceParser
from ..parsing.ocr_service import VisionOCRService
from ..query.query_analyzer import QueryUnderstandingService
from ..retrieval.hybrid_search import HybridSearchService
from ..retrieval.models import RerankWeights
from ..retrieval.rerank_service import RerankerService
from ..retrieval.keyword_search import KeywordIndexCache
from ..retrieval.reranker import BaseReranker, CrossEncoderReranker, LocalReranker, OpenAIReranker
from ..retrieval.retriever import Retriever
from ..retrieval.semantic_search import SemanticSearchService
from ..security.tokens import TokenService
from ..storage.repositories import (
    SqlAlchemyChatRepository,
    SqlAlchemyChunkRepository,
    SqlAlchemyMessageRepository,
    SqlAlchemyUserRepository,
)
from ..storage.vector_synced_chunk_repository import VectorSyncedChunkRepository
from ..vector.client import QdrantConnectionConfig, build_qdrant_client
from ..vector.models import CollectionConfig
from ..vector.repository import QdrantRepository
from ..vector.service import QdrantService
from ..vectorstore.qdrant_vector_store import QdrantVectorStore

# ---------------- Stateless singletons (built once) ----------------

_openai_client = build_openai_client(settings)
_embedding_service = OpenAIEmbeddingService(_openai_client, settings.embed_model)
_llm_service = OpenAILLMService(_openai_client, settings.chat_model)
_ocr_service = VisionOCRService(_llm_service)
_document_parser = DocumentIntelligenceParser(_ocr_service)

_qdrant_client = build_qdrant_client(
    QdrantConnectionConfig(
        url=settings.qdrant_url,
        port=settings.qdrant_port,
        grpc_port=settings.qdrant_grpc_port,
        api_key=settings.qdrant_api_key,
        https=settings.qdrant_https,
        timeout=settings.qdrant_timeout_seconds,
        max_retries=settings.qdrant_max_retries,
        retry_backoff_seconds=settings.qdrant_retry_backoff_seconds,
    )
)
_qdrant_repository = QdrantRepository(
    _qdrant_client,
    max_retries=settings.qdrant_max_retries,
    retry_backoff_seconds=settings.qdrant_retry_backoff_seconds,
)
_qdrant_collection_config = CollectionConfig(
    name=settings.qdrant_collection,
    vector_size=settings.qdrant_vector_size,
    distance=settings.qdrant_distance,
    hnsw_m=settings.qdrant_hnsw_m,
    hnsw_ef_construct=settings.qdrant_hnsw_ef_construct,
    search_ef=settings.qdrant_search_ef,
)
_qdrant_service = QdrantService(
    _qdrant_repository, _qdrant_collection_config, batch_size=settings.qdrant_batch_size
)
_vector_store = QdrantVectorStore(_qdrant_service)

_token_service = TokenService(settings)
_semantic_search = SemanticSearchService(_vector_store)
_keyword_index_cache = KeywordIndexCache()


def _build_reranker() -> BaseReranker:
    """Provider selection lives in exactly one place — swapping
    RERANK_PROVIDER never requires touching hybrid_search.py or
    rerank_service.py. CrossEncoderReranker itself lazy-loads its model
    on first use (see reranker.py) regardless of when this singleton is
    constructed, so building it here at import time does not trigger a
    model download at startup."""
    if settings.rerank_provider == "cross_encoder":
        return CrossEncoderReranker(settings.cross_encoder_model_name)
    if settings.rerank_provider == "openai":
        return OpenAIReranker(_llm_service)
    return LocalReranker()


_rerank_weights = RerankWeights(
    semantic_weight=settings.rerank_semantic_weight,
    keyword_weight=settings.rerank_keyword_weight,
    rerank_weight=settings.rerank_weight,
)
_reranker_service = RerankerService(_build_reranker(), _rerank_weights)
_hybrid_search = HybridSearchService(_semantic_search, _keyword_index_cache, _reranker_service)
_context_manager = ContextManagerService()
_citation_validator = CitationValidatorService()
_claim_verifier = ClaimVerificationService(_llm_service)
_answer_generator = AnswerGeneratorService(_llm_service, _citation_validator, _claim_verifier)
_query_understanding = QueryUnderstandingService(_llm_service)
_long_context_analyzer = LongContextAnalyzer()
_long_context_summarizer = LongContextSummarizer(_llm_service)
_long_context_cache = LongContextCache()
_study_guide_generator = StudyGuideGenerator(_llm_service, _long_context_summarizer)


# ---------------- Per-request repositories ----------------

def get_chat_repository(db: Session = Depends(get_db)) -> SqlAlchemyChatRepository:
    return SqlAlchemyChatRepository(db)


def get_chunk_repository(db: Session = Depends(get_db)) -> VectorSyncedChunkRepository:
    """Wraps the SQLite repository so every save/delete also reaches
    Qdrant (spec items 6, 10, 11) — see storage/vector_synced_chunk_repository.py.
    `ChunkRepository` callers (ChatService, Retriever) depend on the
    Protocol, not this concrete type, so this swap is invisible to them."""
    return VectorSyncedChunkRepository(SqlAlchemyChunkRepository(db), _qdrant_service)


def get_message_repository(db: Session = Depends(get_db)) -> SqlAlchemyMessageRepository:
    return SqlAlchemyMessageRepository(db)


def get_user_repository(db: Session = Depends(get_db)) -> SqlAlchemyUserRepository:
    return SqlAlchemyUserRepository(db)


# ---------------- Per-request application services ----------------

def get_summarization_service() -> SummarizationService:
    return SummarizationService(_llm_service)


def get_retriever() -> Retriever:
    return Retriever(_embedding_service, _llm_service, _hybrid_search, _query_understanding)


def get_chat_service(
    chat_repo: SqlAlchemyChatRepository = Depends(get_chat_repository),
    chunk_repo: VectorSyncedChunkRepository = Depends(get_chunk_repository),
    summarizer: SummarizationService = Depends(get_summarization_service),
) -> ChatService:
    return ChatService(chat_repo, chunk_repo, _document_parser, _embedding_service, summarizer, _keyword_index_cache)


def get_qa_service(
    retriever: Retriever = Depends(get_retriever),
    summarizer: SummarizationService = Depends(get_summarization_service),
    message_repo: SqlAlchemyMessageRepository = Depends(get_message_repository),
) -> QAService:
    return QAService(
        _llm_service,
        retriever,
        summarizer,
        message_repo,
        _context_manager,
        _answer_generator,
        _long_context_analyzer,
        _long_context_summarizer,
        _long_context_cache,
        _study_guide_generator,
        _claim_verifier,
    )


def get_auth_service(user_repo: SqlAlchemyUserRepository = Depends(get_user_repository)) -> AuthService:
    return AuthService(_token_service, user_repo)


# ---------------- Current-user dependency (used by every protected route) ----------------

def get_current_user(
    authorization: str = Header(default=""),
    user_repo: SqlAlchemyUserRepository = Depends(get_user_repository),
) -> models.User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header.")

    token = authorization.removeprefix("Bearer ").strip()
    user_id = _token_service.decode_access_token(token)

    user = user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(401, "User not found.")
    return user

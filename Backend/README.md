# Chat With PDF — FastAPI Backend

This directory contains the backend for **Chat With PDF**, an AI-powered document question-answering system built with **FastAPI**, **OpenAI**, and **Qdrant**.

The backend provides APIs for:

* User authentication
* Chat creation and management
* PDF/document processing
* Semantic and hybrid retrieval
* Qdrant vector search
* Reranking
* Context management
* AI-generated answers
* Citation and grounding validation
* Document summarization
* Long-context document analysis

---

## Architecture

The backend follows a layered architecture:

```text
Client
  │
  ▼
FastAPI API
  │
  ├── Authentication
  ├── Chat API
  └── Message API
  │
  ▼
Application Layer
  │
  ├── QA Service
  ├── Answer Generator
  ├── Chat Service
  ├── Summarization
  └── Claim Verification
  │
  ▼
Query Processing
  │
  ├── Query Analysis
  ├── Intent Classification
  ├── Entity Extraction
  ├── Query Rewriting
  └── Query Planning
  │
  ▼
Retrieval Layer
  │
  ├── Semantic Search
  ├── Keyword Search
  ├── Hybrid Search
  ├── Context Expansion
  └── Reranking
  │
  ▼
Vector Store
  │
  └── Qdrant
  │
  ▼
LLM
  │
  └── OpenAI
```

---

## Project Structure

```text
Backend/
│
├── app/
│   ├── api/
│   │   ├── routers/
│   │   │   ├── auth.py
│   │   │   ├── chats.py
│   │   │   └── messages.py
│   │   └── deps.py
│   │
│   ├── application/
│   │   ├── answer_generator_service.py
│   │   ├── auth_service.py
│   │   ├── chat_service.py
│   │   ├── citation_validator_service.py
│   │   ├── claim_verification_service.py
│   │   ├── prompts.py
│   │   ├── qa_service.py
│   │   └── summarization_service.py
│   │
│   ├── context/
│   │   ├── answer_style.py
│   │   ├── context_compressor.py
│   │   ├── context_manager.py
│   │   ├── context_ranker.py
│   │   ├── conversation_context_builder.py
│   │   └── token_utils.py
│   │
│   ├── domain/
│   │   ├── citations.py
│   │   ├── entities.py
│   │   └── interfaces.py
│   │
│   ├── llm/
│   │   └── openai_services.py
│   │
│   ├── longcontext/
│   │   ├── chapter_outline_generator.py
│   │   ├── chapter_retriever.py
│   │   ├── long_context_analyzer.py
│   │   ├── map_reduce_summarizer.py
│   │   ├── page_range_retriever.py
│   │   └── study_guide_generator.py
│   │
│   ├── parsing/
│   │   ├── document_parser_v2.py
│   │   ├── pymupdf_parser.py
│   │   ├── ocr_service.py
│   │   ├── layout_parser.py
│   │   ├── table_extractor.py
│   │   ├── semantic_chunker.py
│   │   └── quality_gate.py
│   │
│   ├── query/
│   │   ├── entity_extractor.py
│   │   ├── intent_classifier.py
│   │   ├── query_analyzer.py
│   │   ├── query_planner.py
│   │   └── query_rewriter.py
│   │
│   ├── retrieval/
│   │   ├── semantic_search.py
│   │   ├── keyword_search.py
│   │   ├── hybrid_search.py
│   │   ├── retriever.py
│   │   ├── reranker.py
│   │   └── context_expander.py
│   │
│   ├── storage/
│   ├── vector/
│   ├── vectorstore/
│   │   └── qdrant_vector_store.py
│   │
│   ├── config.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   └── main.py
│
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Requirements

* Python 3.11+
* Docker Desktop
* Docker Compose
* Qdrant
* OpenAI API key

For production deployment, the backend can be containerized and deployed to Google Cloud Run or another container platform.

---

## Environment Variables

Create a `.env` file inside `Backend/`.

Example:

```env
OPENAI_API_KEY=your_openai_api_key

DATABASE_URL=your_database_url

QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=

JWT_SECRET_KEY=your_secret_key
```

**Never commit `.env` or API keys to GitHub.**

The repository should contain only an example configuration such as:

```text
.env.example
```

---

## Running with Docker

From the `Backend` directory:

```powershell
cd Backend
```

Start the backend and Qdrant:

```powershell
docker compose up --build
```

The FastAPI server will normally be available at:

```text
http://localhost:8000
```

FastAPI Swagger documentation:

```text
http://localhost:8000/docs
```

ReDoc:

```text
http://localhost:8000/redoc
```

---

## Running in the Background

```powershell
docker compose up -d --build
```

View logs:

```powershell
docker compose logs -f app
```

View all services:

```powershell
docker compose ps
```

Stop the services:

```powershell
docker compose down
```

---

## Qdrant

Qdrant is used as the vector database for semantic document retrieval.

When running through Docker Compose, the backend communicates with Qdrant using:

```text
http://qdrant:6333
```

The Qdrant service should not be exposed unnecessarily in production.

For local development, the Qdrant dashboard/API is normally available at:

```text
http://localhost:6333
```

---

## RAG Pipeline

The question-answering pipeline follows these major stages:

```text
User Question
      │
      ▼
Query Analysis
      │
      ▼
Intent / Entity Detection
      │
      ▼
Query Rewriting
      │
      ▼
Semantic + Keyword Retrieval
      │
      ▼
Qdrant Vector Search
      │
      ▼
Context Expansion
      │
      ▼
Reranking
      │
      ▼
Context Compression
      │
      ▼
LLM Answer Generation
      │
      ▼
Claim Verification
      │
      ▼
Citation Validation
      │
      ▼
Final Answer
```

The system is designed to ground generated answers in retrieved document evidence rather than relying only on the model's general knowledge.

---

## PDF Processing

The document processing pipeline supports:

* PDF text extraction
* Physical page tracking
* Arabic and English documents
* OCR when required
* Layout analysis
* Tables
* Images
* Semantic chunking
* Document hierarchy
* Quality checks

The system preserves the physical PDF page associated with each chunk so that generated answers can provide page references.

Example:

```text
[p. 17]
```

The page reference represents the physical PDF page used as evidence.

---

## Citations and Grounding

The backend includes citation validation and claim verification.

Important components include:

```text
citation_validator_service.py
claim_verification_service.py
domain/citations.py
```

The intended flow is:

```text
Retrieved Evidence
       │
       ▼
Generated Claim
       │
       ▼
Claim Verification
       │
       ▼
Citation Validation
       │
       ▼
Final Grounded Answer
```

This helps reduce unsupported statements and citation mismatches.

---

## API

The main API application is:

```text
app/main.py
```

Main API areas include:

```text
/auth
/chats
/messages
```

Interactive API documentation is available through:

```text
/docs
```

when the server is running.

---

## Local Development Without Docker

Create a virtual environment:

```powershell
python -m venv .venv
```

Activate it on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

Start FastAPI:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Testing

Run the test suite from the backend directory:

```powershell
pytest
```

For verbose output:

```powershell
pytest -v
```

---

## Docker Image

Build the backend image:

```powershell
docker build -t chat-with-pdf-backend .
```

Run it:

```powershell
docker run --env-file .env -p 8000:8000 chat-with-pdf-backend
```

---

## Cloud Run Deployment

The backend is containerized and can be deployed to Google Cloud Run.

A typical workflow is:

```text
Backend Source
      │
      ▼
Docker Build
      │
      ▼
Container Image
      │
      ▼
Google Artifact Registry
      │
      ▼
Cloud Run
```

For production deployment, environment variables and secrets should be supplied through Cloud Run configuration or Google Secret Manager rather than committing them to the repository.

Qdrant should also be configured as a production service rather than relying on local Docker storage.

---

## Security

Do not commit:

```text
.env
*.pem
*.key
credentials.json
service-account.json
```

Do not expose:

* OpenAI API keys
* Database passwords
* JWT secrets
* Firebase credentials
* Qdrant API keys

Use environment variables or a secret-management service.

---

## Technology Stack

| Component           | Technology                        |
| ------------------- | --------------------------------- |
| API                 | FastAPI                           |
| Language            | Python                            |
| LLM                 | OpenAI                            |
| Vector Database     | Qdrant                            |
| PDF Processing      | PyMuPDF / custom parsing pipeline |
| OCR                 | OCR service                       |
| Retrieval           | Semantic + Keyword + Hybrid       |
| Reranking           | Configurable reranker             |
| Containerization    | Docker                            |
| Local orchestration | Docker Compose                    |
| Production option   | Google Cloud Run                  |

---

## Relationship With Flutter

The Flutter application is located in the parent repository:

```text
../Flutter
```

The architecture is:

```text
Flutter Application
        │
        │ HTTP/REST
        ▼
FastAPI Backend
        │
        ├── PostgreSQL / Database
        ├── Qdrant
        └── OpenAI
```

The Flutter application should communicate with the backend through the configured API base URL.

---

## Repository

This backend is part of the main Chat With PDF repository:

```text
chat-With-pdf/
├── Flutter/
└── Backend/
```

The repository contains both the Flutter client and the FastAPI backend.

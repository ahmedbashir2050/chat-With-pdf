<<<<<<< HEAD
# chat_with_pdf

A new Flutter project.

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Learn Flutter](https://docs.flutter.dev/get-started/learn-flutter)
- [Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Flutter learning resources](https://docs.flutter.dev/reference/learning-resources)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.
=======
# Chat with PDF

An AI-powered Flutter application that allows users to upload PDF documents and interact with them through an intelligent chat interface.

The project uses **Retrieval-Augmented Generation (RAG)** to retrieve relevant information from uploaded documents and generate grounded answers with PDF page citations.

## ✨ Features

* 📄 Upload and process PDF documents
* 🤖 AI-powered question answering
* 🔍 Retrieval-Augmented Generation (RAG)
* 🧠 Semantic search using vector embeddings
* 🗄️ Qdrant vector database integration
* 📑 PDF page-based citations
* 🌐 Arabic and English language support
* 💬 Document-based conversations
* 📱 Flutter cross-platform interface
* ⚡ FastAPI backend
* 🔐 User authentication
* 📚 Chat history

## 🏗️ Architecture

```text
Flutter Application
       │
       │ HTTP / REST API
       ▼
   FastAPI Backend
       │
       ├── PDF Parser
       ├── Text Chunking
       ├── Embedding Model
       ├── Semantic Search
       ├── Reranking
       └── LLM
              │
              ▼
         Qdrant Vector DB
```

## 🔄 RAG Workflow

```text
PDF Upload
    ↓
PDF Parsing
    ↓
Text Extraction / OCR
    ↓
Text Chunking
    ↓
Generate Embeddings
    ↓
Store Vectors in Qdrant
    ↓
User Question
    ↓
Query Processing
    ↓
Vector Search
    ↓
Reranking
    ↓
Relevant Context
    ↓
LLM
    ↓
Grounded Answer + Page Citations
```

## 🛠️ Technologies

### Frontend

* Flutter
* Dart
* Material Design
* Markdown rendering
* REST API

### Backend

* Python
* FastAPI
* Docker
* Qdrant
* Vector embeddings
* LLM integration
* PDF processing
* OCR

### Database

* Qdrant for vector search
* Relational/database storage for application data

## 📂 Project Structure

```text
chat_with_pdf/
│
├── lib/
│   ├── controllers/
│   ├── screens/
│   ├── services/
│   ├── widgets/
│   ├── models/
│   └── main.dart
│
├── android/
├── ios/
├── web/
├── test/
├── pubspec.yaml
└── README.md
```

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/chat_with_pdf.git
cd chat_with_pdf
```

### 2. Install Flutter dependencies

```bash
flutter pub get
```

### 3. Configure the backend

Start the FastAPI backend and Qdrant services according to the backend project configuration.

### 4. Configure environment variables

Create the required environment configuration without committing secrets to GitHub.

For example:

```text
API_BASE_URL=your_backend_url
```

**Never commit API keys, passwords, private credentials, or `.env` files to the repository.**

### 5. Run the Flutter application

```bash
flutter run
```

For Flutter Web:

```bash
flutter run -d chrome
```

## 🧪 Testing

Run Flutter tests with:

```bash
flutter test
```

You can also analyze the project with:

```bash
flutter analyze
```

## 🌍 Language Support

The application is designed to support:

* English
* Arabic
* RTL interfaces

The RAG pipeline is designed to work with multilingual PDF documents and provide answers grounded in the uploaded document.

## 📑 Citations

Answers generated from documents can include physical PDF page references such as:

```text
[p. 5]
```

These references allow users to identify the source page of information used to generate an answer.

## 🎯 Project Goal

The main goal of this project is to build a practical AI-powered document assistant that combines:

* Large Language Models
* Retrieval-Augmented Generation
* Vector databases
* Semantic search
* Document intelligence
* PDF processing
* Flutter application development

The project demonstrates how modern AI technologies can be integrated into a complete end-to-end application.

## 👨‍💻 Author

**Ahmed Bashir Ibrahim Aboalgasim**

GitHub: https://github.com/ahmedbashir2050

## 📄 License

This project is currently intended for educational and research purposes.
>>>>>>> 54e346f8eabd62d56d6d577cc96275585eca68d8

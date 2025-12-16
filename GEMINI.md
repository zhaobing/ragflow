# RAGFlow Project Overview

This document provides a comprehensive overview of the RAGFlow project, its architecture, and instructions for building, running, and developing the application.

## 1. Project Purpose and Key Features

RAGFlow is an open-source Retrieval-Augmented Generation (RAG) engine designed to create a superior context layer for Large Language Models (LLMs). It offers a streamlined RAG workflow adaptable to enterprises of any scale, enabling developers to transform complex data into high-fidelity, production-ready AI systems.

**Key Features:**

*   **Deep Document Understanding:** Advanced knowledge extraction from unstructured data with complex formats.
*   **Template-based Chunking:** Intelligent and explainable text chunking with multiple template options.
*   **Grounded Citations:** Visualization of text chunking to allow human intervention and traceable citations to support grounded answers.
*   **Heterogeneous Data Source Compatibility:** Supports a wide range of data sources, including Word, slides, excel, txt, images, scanned copies, structured data, and web pages.
*   **Automated RAG Workflow:** A streamlined and automated RAG orchestration for both personal and large-scale business use cases.

## 2. Architecture

RAGFlow is a containerized application orchestrated using Docker Compose. The architecture consists of a main application service (`ragflow-cpu` or `ragflow-gpu`) and several backing services:

*   **Application Server:** The core application logic, built with Python and the Flask/Quart web framework.
*   **Database:** MySQL is used as the primary database for storing metadata and application data.
*   **Document and Vector Store:** RAGFlow supports multiple backends for storing and indexing documents and vectors, including:
    *   Elasticsearch
    *   OpenSearch
    *   Infinity
*   **Object Storage:** MinIO is used for storing unstructured data like documents and images.
*   **Cache:** Redis (Valkey) is used for caching to improve performance.
*   **Other Services:** The system also includes services for:
    *   **Text-Embedding-Inference (TEI):** A dedicated service for generating text embeddings.
    *   **Sandbox Executor Manager:** A service for executing code in a sandboxed environment.
    *   **Kibana:** A tool for visualizing data from Elasticsearch.

## 3. Building and Running

### 3.1. Prerequisites

*   CPU >= 4 cores
*   RAM >= 16 GB
*   Disk >= 50 GB
*   Docker >= 24.0.0
*   Docker Compose >= v2.26.1

### 3.2. Running with Docker

The recommended way to run RAGFlow is by using the pre-built Docker images.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/infiniflow/ragflow.git
    cd ragflow/docker
    ```

2.  **Start the services:**
    ```bash
    # For CPU-based execution
    docker compose -f docker-compose.yml up -d

    # For GPU-based execution
    # sed -i '1i DEVICE=gpu' .env
    # docker compose -f docker-compose.yml up -d
    ```

3.  **Access the application:**
    Open your web browser and navigate to `http://<your-server-ip>`.

### 3.3. Building from Source (for Development)

For development purposes, you can build and run the services from the source code.

1.  **Install dependencies:**
    *   Install `uv` and `pre-commit`: `pipx install uv pre-commit`
    *   Install Python dependencies: `uv sync --python 3.12`
    *   Download additional dependencies: `uv run download_deps.py`
    *   Install pre-commit hooks: `pre-commit install`

2.  **Launch backing services:**
    ```bash
    docker compose -f docker/docker-compose-base.yml up -d
    ```

3.  **Launch the backend service:**
    ```bash
    source .venv/bin/activate
    export PYTHONPATH=$(pwd)
    bash docker/launch_backend_service.sh
    ```

4.  **Launch the frontend service:**
    ```bash
    cd web
    npm install
    npm run dev
    ```

## 4. Development Conventions

### 4.1. Coding Style

*   **Python:** The project uses `ruff` for linting and code formatting. The configuration can be found in the `pyproject.toml` file.
*   **Frontend:** The frontend code follows standard JavaScript/TypeScript conventions.

### 4.2. Testing

*   The project uses `pytest` for backend testing.
*   Test files are located in the `test` directory and are named with the `test_*.py` pattern.
*   To run the tests, use the `pytest` command in the root directory of the project.

### 4.3. Project Structure

The project is organized into the following main directories:

*   `api/`: Contains the backend API server code.
*   `web/`: Contains the frontend web application code.
*   `docker/`: Contains Docker-related files, including `docker-compose.yml` and configuration templates.
*   `rag/`: Contains the core RAG logic.
*   `deepdoc/`: Contains the deep document understanding module.
*   `agent/`: Contains the agent framework.
*   `graphrag/`: Contains the graph RAG module.
*   `common/`: Contains common utilities and modules shared across the project.
*   `test/`: Contains the test suite for the project.

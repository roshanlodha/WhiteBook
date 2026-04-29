# WhiteBook

WhiteBook is a local AI-powered assistant designed for emergency medicine, featuring a high-performance inference engine and context-aware retrieval.

## Project Overview

The system uses a local Qwen3 model to provide clinical assistance and reasoning, with a focus on high data density and minimalist design.

## Features

- **Local Inference**: Powered by Qwen3 GGUF models.
- **Reasoning Visualization**: Displays the model's thinking process (<think> tags).
- **Context Retrieval**: Integrates with a local knowledge base for accurate information.

## Getting Started

### Prerequisites

- Python 3.x
- Virtual environment (`env/`)
- GGUF model file (e.g., `Qwen3-8B-Q4_K_M.gguf`)

### Running the Application

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## TODO

- [ ] implement calculator

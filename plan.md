### **Phase 1: The Offline Ingestion Pipeline**
> "We are building an offline data ingestion pipeline for an iOS application. Act as a senior data engineer. Write a Python script (`ingest_to_sqlite.py`) that processes a PDF and outputs a SQLite database and an image directory.
> 
> **Environment & Setup:**
> 1. Use the following libraries: `docling`, `sentence-transformers`, `pandas`, `Pillow`, and `numpy`.
> 2. Initialize a SQLite database `staffbook_kb.sqlite` with a `chunks` table: `id` (TEXT PRIMARY KEY), `heading_context` (TEXT), `text_content` (TEXT), `page_start` (INTEGER), `page_end` (INTEGER), `image_filename` (TEXT), and `embedding` (BLOB). Create an `ios_images` directory.
> 
> **Extraction & Chunking:**
> 1. Configure Docling's `DocumentConverter` with `PdfPipelineOptions(generate_picture_images=True, generate_table_images=True)`.
> 2. Parse the PDF and use Docling's `HierarchicalChunker` to chunk the text.
> 3. For each chunk, extract the structural headings from `chunk.meta.headings` and prepend it as context (e.g., '[Cardiology > ACLS] chunk text'). 
> 4. If the chunk contains an `item.image` in its metadata, save that specific PIL image bounding box to `ios_images/item_{id}.png` and store the filename.
> 
> **Embedding:**
> 1. Load `Alibaba-NLP/gte-modernbert-base` via `SentenceTransformer(trust_remote_code=True)`.
> 2. Generate embeddings for the text content, convert them to `float32` bytes using NumPy, and insert the records into the SQLite database. Provide the complete, runnable Python code."

### **Phase 2: iOS Initialization & Database Bridge**
> "We are transitioning to Xcode to build the iOS app. 
> 
> **Project Setup:**
> 1. Provide instructions to create a new iOS Swift project targeting iOS 17.0+. 
> 2. Add `SQLite.swift` via Swift Package Manager.
> 
> **Database Integration (`DatabaseService.swift`):**
> 1. Instruct how to add `staffbook_kb.sqlite` and the `ios_images` folder into the Xcode project bundle.
> 2. Write a `DatabaseService` that locates the SQLite file in `Bundle.main`, copies it to the app's `DocumentDirectory` on first launch, and opens a connection.
> 3. Define the Swift data models matching our schema. Implement a function to retrieve text chunks by ID, returning the text, heading context, and any associated `image_filename`. Provide the robust Swift code."

### **Phase 3: CoreML & Native Vector Search**
> "Implement on-device vector search.
> 
> **Embedding Extraction (`EmbeddingService.swift`):**
> 1. Assume we have converted `Alibaba-NLP/gte-modernbert-base` into a CoreML `.mlpackage` and added it to the bundle.
> 2. Write an `EmbeddingService.swift` class that takes a user query, tokenizes it, runs it through the CoreML model, and returns a `[Float32]` array.
> 
> **Vector Matching (`SearchService.swift`):**
> 1. Write a high-performance native Swift cosine similarity function.
> 2. Write a `search(query: String)` function that embeds the query, fetches all BLOBs from `DatabaseService`, calculates similarities in a background `Task`, and returns the top 3 most relevant text chunks."

### **Phase 4: Qwen3 Local Inference Engine**
> "Integrate the generative AI engine.
> 
> **Setup:**
> 1. Add the latest version of `llama.cpp` to the project via SPM. 
> 2. Assume we have added `Qwen3-4B-Instruct-Q4_K_M.gguf` to the bundle.
> 
> **Inference Wrapper (`LLMService.swift`):**
> 1. Write an `LLMService` class that initializes the context with `GGML_USE_METAL` enabled for GPU acceleration.
> 2. Write a function `generate(query: String, context: [Chunk]) -> AsyncStream<String>`. 
> 3. The system prompt must be: 'You are an emergency medicine assistant. Answer strictly using the provided context chunks. If the context relies on a visual diagram, explicitly state the user should reference the attached image.'
> 4. Ensure the prompt generation respects the Qwen3 chat template, specifically setting up the inference to yield the `<think>` reasoning tokens as well as the final output."

### **Phase 5: The Interface & Visual Routing**
> "Design the main SwiftUI interface. The design system must be strictly 'minimalist maximalism'—high data density, stark geometry, and zero visual clutter.
> 
> **Styling:**
> 1. Use pure black or white backgrounds with heavy reliance on Apple's SF Pro font weights to establish hierarchy.
> 2. Use pastel orange strictly as the primary accent color for active states, user bubbles, and highlighting the model's `<think>` reasoning block.
> 
> **Views (`ChatView.swift` & `ContextCard.swift`):**
> 1. Create a `ChatView` that handles the streaming `AsyncStream` response. It must actively parse the incoming text: anything between `<think>` and `</think>` should be styled in italicized pastel orange to represent the model's clinical reasoning process, while the final answer renders in standard text.
> 2. Implement a `ContextCard` view below the chat output to display the retrieved chunks. If a chunk has an `image_filename`, dynamically load and render that exact PNG from the bundle inline. The image must be wrapped in a `MagnificationGesture` for pinch-to-zoom capabilities. Provide the complete SwiftUI code."
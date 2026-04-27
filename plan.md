Phase 1: The Python Virtual Environment & Data Ingestion

This phase builds the offline pipeline to process your PDF, extract images, and package everything into an iOS-ready SQLite database.

Prompt for your Coding Agent:

"We are building the offline data ingestion pipeline for an iOS application named 'staffbook'. Act as a senior data engineer. Your task is to write a Python script that processes a medical PDF and outputs a pre-packaged SQLite database and an image directory.

Environment Setup:

Create a requirements.txt with the following pinned dependencies: pymupdf==1.23.8, sentence-transformers==2.5.1, pandas==2.2.1, Pillow==10.2.0, torch, and coremltools==7.1.

Output the exact terminal commands to create a Python 3.11 virtual environment, activate it, and install these requirements.

The Ingestion Script (ingest_to_sqlite.py):

Initialize a SQLite database named staffbook_kb.sqlite. Create a table named chunks with columns: id (TEXT PRIMARY KEY), text_content (TEXT), page_start (INTEGER), page_end (INTEGER), has_image (BOOLEAN), and embedding (BLOB).

Create an output directory called ios_images.

Use PyMuPDF (fitz) to iterate through the provided PDF. Extract the text and apply semantic chunking (target ~400 tokens per chunk, 50-token overlap).

For every page, use PyMuPDF to extract the page as a high-res PNG and save it to ios_images/page_{page_number}.png. Set the has_image boolean to True for chunks belonging to that page.

Load the nomic-ai/nomic-embed-text-v1.5 model using sentence-transformers. Ensure you pass trust_remote_code=True and configure it to output 768-dimensional embeddings.

Generate embeddings for every text chunk, convert the resulting NumPy arrays to bytes (using numpy.ndarray.tobytes() with float32 dtype), and insert the records into the SQLite database.

Provide the complete, runnable Python code and the exact command to execute it."

Phase 2: iOS Project Initialization & Core Data Base

This phase sets up the Xcode environment and bridges the offline database into Swift.

Prompt for your Coding Agent:

"We are now moving to Xcode. Act as a Lead iOS Developer.

Project Setup:

Provide instructions to create a new iOS App project in Xcode 15+. Name the project 'staffbook'.

The Minimum Deployment Target MUST be strictly set to iOS 17.0.

Interface: SwiftUI. Language: Swift. Storage: None (we are using our own SQLite).

Add the SQLite.swift package via Swift Package Manager (URL: https://github.com/stephencelis/SQLite.swift).

Database Integration (DatabaseService.swift):

Instruct the user to drag and drop staffbook_kb.sqlite and the ios_images folder into the Xcode project, ensuring 'Copy items if needed' and 'Create folder references' are checked.

Write a highly robust DatabaseService.swift class. It must locate staffbook_kb.sqlite in the Bundle.main, copy it to the app's DocumentDirectory on first launch (to avoid read-only bundle restrictions), and open a connection using SQLite.swift.

Define the Swift data models that map exactly to our SQLite schema.

Implement a function to retrieve text chunks by ID, and a function to check if a specific page_{X}.png exists in the local bundle.

Provide the complete Swift code and explicit setup instructions."

Phase 3: On-Device Vector Search

This phase implements the mathematical matching of the user's query to the medical database.

Prompt for your Coding Agent:

"We need to implement local vector search inside the 'staffbook' iOS app.

CoreML Embedding Service (EmbeddingService.swift):

Provide instructions for using the huggingface/coreml python utilities (or similar) to export nomic-embed-text-v1.5 into a .mlpackage optimized for Apple Silicon/Neural Engine.

Once the .mlpackage is dragged into Xcode, write an EmbeddingService.swift class. This class must take a user's String query, tokenize it, feed it to the CoreML model, and return a [Float32] vector of size 768.

Vector Similarity (SearchService.swift):

Write a SearchService.swift class.

Implement an highly optimized, native Swift cosine similarity function func cosineSimilarity(a: [Float32], b: [Float32]) -> Float.

Write a search(query: String, topK: Int) function. This function must:
a. Call EmbeddingService to get the query vector.
b. Fetch all embeddings from DatabaseService. Convert the SQLite BLOBs back into [Float32].
c. Calculate the cosine similarity for all records in a background Task (to avoid blocking the main thread).
d. Return the top 3 most relevant text chunks, sorted by similarity score.

Provide the exact Swift code for these services, utilizing async/await concurrency."

Phase 4: Llama.cpp Local Inference

This connects the retrieval system to the generative LLM using Metal acceleration.

Prompt for your Coding Agent:

"We are integrating the local LLM for generation.

Dependency & Model Setup:

Add llama.cpp to the Xcode project via SPM. Use the official repository (https://github.com/ggerganov/llama.cpp.git).

Instruct the user to download the Qwen2.5-7B-Instruct-Q4_K_M.gguf model and drag it into the Xcode project bundle.

Inference Engine (LLMService.swift):

Write an LLMService.swift class wrapper around the llama.cpp C-API.

Initialization MUST enable Metal (GGML_USE_METAL) so the model runs on the GPU.

The system prompt must be hardcoded as: 'You are an elite emergency medicine resident. Answer the clinical query strictly using the provided context chunks. If the context relies on an image, explicitly tell the user to reference the attached image.'

Write a generateResponse(query: String, context: [Chunk]) -> AsyncStream<String> function. It must format the Qwen prompt template correctly (<|im_start|>system...<|im_end|><|im_start|>user...), feed the retrieved context and query, and yield generated tokens in real-time.

Provide the complete wrapper implementation."

Phase 5: The Interface

This final phase constructs the UI based on your specific design preferences.

Prompt for your Coding Agent:

"Design the main SwiftUI interface for the 'staffbook' app.

Design System:
The UI must strictly follow a 'minimalist maximalism' aesthetic. High data density, sharp geometric components, and zero visual clutter.

Backgrounds should be stark (pure black or pure white).

Typography must use Apple's San Francisco (SF Pro) font with distinct weight hierarchies.

Use the color pastel orange (Color(hex: "#FFB347") or similar) strictly as the primary accent color for user message bubbles, active loading states, and critical clinical alerts.

Views (ChatView.swift & ContextCard.swift):

Create a ChatView that handles user input and displays a scrolling list of messages. It must observe the AsyncStream from LLMService to type out the response token-by-token.

Below the LLM's response in the chat feed, implement a ContextCard view. This displays the top retrieved chunks used to generate the answer.

Crucial: If a retrieved chunk has has_image == true, the ContextCard must dynamically load page_{X}.png from the ios_images bundle folder and display it inline. The image must be wrapped in a MagnificationGesture so the user can pinch-to-zoom to read detailed EKGs or flowcharts.

Provide the complete SwiftUI code for the main views, ensuring all view models are cleanly separated."
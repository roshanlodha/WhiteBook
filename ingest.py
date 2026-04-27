import fitz  # PyMuPDF
import sqlite3
import os
import uuid
import numpy as np
from sentence_transformers import SentenceTransformer

# --- Configuration ---
PDF_PATH = "WhiteBook.pdf"
DB_PATH = "staffbook_kb.sqlite"
IMAGE_DIR = "images"
MODEL_NAME = "Alibaba-NLP/gte-modernbert-base"

# Target ~400 tokens (approx 300 words), 50 token overlap (approx 35 words)
CHUNK_SIZE_WORDS = 300
OVERLAP_WORDS = 35

def setup_database():
    """Initializes the SQLite database and creates the chunks table."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH) # Start fresh each run
        print(f"Removed old database: {DB_PATH}")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE chunks (
            id TEXT PRIMARY KEY,
            text_content TEXT,
            page_start INTEGER,
            page_end INTEGER,
            has_image BOOLEAN,
            embedding BLOB
        )
    """)
    conn.commit()
    return conn

def setup_directories():
    """Creates the image output directory if it doesn't exist."""
    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)
        print(f"Created directory: {IMAGE_DIR}")

def chunk_text(text, page_num):
    """Splits text into overlapping word-based chunks."""
    words = text.split()
    chunks = []
    
    if not words:
        return chunks

    for i in range(0, len(words), CHUNK_SIZE_WORDS - OVERLAP_WORDS):
        chunk_words = words[i:i + CHUNK_SIZE_WORDS]
        chunk_text = " ".join(chunk_words)
        if len(chunk_text.strip()) > 0:
            chunks.append({
                "id": str(uuid.uuid4()),
                "text": chunk_text,
                "page": page_num
            })
        
        # Stop if we've reached the end of the text
        if i + CHUNK_SIZE_WORDS >= len(words):
            break
            
    return chunks

def main():
    print(f"Starting ingestion pipeline for {PDF_PATH}...")
    
    if not os.path.exists(PDF_PATH):
        raise FileNotFoundError(f"Could not find {PDF_PATH} in the current directory.")

    setup_directories()
    conn = setup_database()
    cursor = conn.cursor()
    
    # 1. Load the embedding model
    print(f"Loading embedding model: {MODEL_NAME}...")
    # trust_remote_code=True is required for Nomic models
    model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)
    
    # 2. Process the PDF
    print("Extracting text, images, and generating chunks...")
    doc = fitz.open(PDF_PATH)
    all_chunks = []
    
    for page_index in range(len(doc)):
        page_num = page_index + 1 # 1-indexed for human readability
        page = doc[page_index]
        
        # Extract Image (Render page at 150 DPI)
        pix = page.get_pixmap(dpi=150)
        image_path = os.path.join(IMAGE_DIR, f"page_{page_num}.png")
        pix.save(image_path)
        
        # Extract Text
        text = page.get_text("text")
        
        # Chunk Text
        page_chunks = chunk_text(text, page_num)
        all_chunks.extend(page_chunks)
        
        if page_num % 10 == 0 or page_num == len(doc):
            print(f"Processed page {page_num}/{len(doc)}")

    # 3. Generate Embeddings and Insert to DB
    print(f"Generating embeddings for {len(all_chunks)} chunks...")
    
    for i, chunk in enumerate(all_chunks):
        # Nomic performs best with the 'search_document: ' prefix for the corpus
        embedding_input = "search_document: " + chunk["text"]
        
        # Generate embedding
        embedding = model.encode(embedding_input)
        
        # Convert to float32 bytes for SQLite BLOB storage
        embedding_blob = embedding.astype(np.float32).tobytes()
        
        # Insert into database
        cursor.execute("""
            INSERT INTO chunks (id, text_content, page_start, page_end, has_image, embedding)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            chunk["id"], 
            chunk["text"], 
            chunk["page"], 
            chunk["page"], 
            True, # True because we rendered an image for every page
            embedding_blob
        ))
        
        if (i + 1) % 50 == 0:
            print(f"Embedded and saved {i + 1}/{len(all_chunks)} chunks...")
            
    conn.commit()
    conn.close()
    doc.close()
    
    print("\n--- Pipeline Complete ---")
    print(f"Database saved to: {DB_PATH}")
    print(f"Images saved to: ./{IMAGE_DIR}/")

if __name__ == "__main__":
    main()
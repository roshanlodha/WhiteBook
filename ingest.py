import os
import sqlite3
import uuid
import numpy as np
from sentence_transformers import SentenceTransformer
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.chunking import HierarchicalChunker

# --- Configuration ---
PDF_PATH = "WhiteBook.pdf"
DB_PATH = "staffbook_kb.sqlite"
IMAGE_DIR = "images"
MODEL_NAME = "Alibaba-NLP/gte-modernbert-base"

def setup_database():
    """Initializes the SQLite database with the advanced schema."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed old database: {DB_PATH}")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Note the change: image_filename instead of has_image for precise mapping
    cursor.execute("""
        CREATE TABLE chunks (
            id TEXT PRIMARY KEY,
            heading_context TEXT,
            text_content TEXT,
            page_start INTEGER,
            page_end INTEGER,
            image_filename TEXT,
            embedding BLOB
        )
    """)
    conn.commit()
    return conn

def setup_directories():
    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)

def main():
    print(f"Starting advanced ingestion pipeline for {PDF_PATH}...")
    setup_directories()
    conn = setup_database()
    cursor = conn.cursor()

    # 1. Load Embedding Model
    print(f"Loading embedding model: {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)

    # 2. Configure Docling for precise image and table extraction
    print("Configuring Docling structural parser...")
    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_picture_images = True
    pipeline_options.generate_table_images = True
    
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    # 3. Parse the PDF Document
    print("Parsing document structure (this may take a moment)...")
    conv_result = converter.convert(PDF_PATH)
    doc = conv_result.document

    # 4. Perform Hierarchical Chunking
    # This automatically groups text under its relevant headers based on the TOC/Formatting
    print("Applying hierarchical chunking...")
    chunker = HierarchicalChunker()
    chunks = list(chunker.chunk(doc))

    print(f"Generated {len(chunks)} structurally-aware chunks. Generating embeddings...")

    for i, chunk in enumerate(chunks):
        chunk_id = str(uuid.uuid4())
        
        # --- Metadata Extraction ---
        # Extract the hierarchical path (e.g., "Cardiology > ACLS > Bradycardia")
        headings = [h.text for h in chunk.meta.headings if h.text]
        heading_context = " > ".join(headings) if headings else "General Reference"
        
        text_content = chunk.text
        if not text_content.strip():
            continue

        # --- Image/Table Extraction ---
        # Look for image or table items specifically within this chunk's bounding boxes
        image_filename = None
        for item in chunk.meta.doc_items:
            if hasattr(item, "image") and item.image is not None:
                image_filename = f"item_{chunk_id}.png"
                image_path = os.path.join(IMAGE_DIR, image_filename)
                # Save the specific figure/table, not the whole page
                item.image.pil_image.save(image_path, format="PNG")
                break # Bind the first major visual item found in this chunk

        # Pages can span multiple items in a chunk
        page_start = chunk.meta.doc_items[0].prov[0].page_no if chunk.meta.doc_items else 0
        page_end = chunk.meta.doc_items[-1].prov[0].page_no if chunk.meta.doc_items else 0

        # --- Contextual Embedding Formulation ---
        # We prepend the heading context so the model links the text to the specific medical topic
        embedding_input = f"search_document: [{heading_context}] {text_content}"
        embedding = model.encode(embedding_input)
        embedding_blob = embedding.astype(np.float32).tobytes()

        # --- Database Insertion ---
        cursor.execute("""
            INSERT INTO chunks (id, heading_context, text_content, page_start, page_end, image_filename, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            chunk_id,
            heading_context,
            text_content,
            page_start,
            page_end,
            image_filename,
            embedding_blob
        ))

        if (i + 1) % 50 == 0:
            print(f"Processed {i + 1}/{len(chunks)} chunks...")

    conn.commit()
    conn.close()
    
    print("\n--- Pipeline Complete ---")
    print(f"Database saved to: {DB_PATH}")
    print(f"Specific figures/tables saved to: ./{IMAGE_DIR}/")

if __name__ == "__main__":
    main()
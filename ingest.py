import os
import sqlite3
import uuid
import numpy as np
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.chunking import HierarchicalChunker

# --- Configuration ---
PDF_PATH = "WhiteBook.pdf"
DB_PATH = "staffbook_kb.sqlite"
IMAGE_DIR = "ios_images"
MODEL_NAME = "Alibaba-NLP/gte-modernbert-base"

# The Noise Banlist - explicitly filter out mobile UI elements
BANLIST = ["Suggest an Edit", "Table of Contents", "Return to Table of Contents"]

def clean_text(text: str) -> str:
    """Removes known UI noise from the text."""
    for banned_phrase in BANLIST:
        text = text.replace(banned_phrase, "")
    return text.strip()

def extract_page_header(chunk) -> str:
    """
    Attempts to extract the overarching page topic based on the first few 
    structural headings Docling identifies on a given page.
    """
    headings = [h for h in chunk.meta.headings if h]
    if headings:
        # Assuming the top level headers capture "Cardiology" and "ACLS: Tachycardia"
        # We take the top 2 levels to form the anchor.
        anchor = " > ".join(headings[:2])
        return anchor
    return "General Medical Reference"

def setup_database():
    """Initializes the SQLite database with the advanced schema."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed old database: {DB_PATH}")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
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
    """Creates the image output directory if it doesn't exist."""
    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)

def main():
    print(f"Starting highly-grounded ingestion pipeline for {PDF_PATH}...")
    setup_directories()
    conn = setup_database()
    cursor = conn.cursor()

    print(f"Loading embedding model: {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)

    print("Configuring Docling structural parser...")
    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_picture_images = True
    pipeline_options.generate_table_images = True
    
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    print("Parsing document structure...")
    conv_result = converter.convert(PDF_PATH)
    doc = conv_result.document

    print("Applying hierarchical chunking...")
    chunker = HierarchicalChunker()
    chunks = list(chunker.chunk(doc))

    for chunk in tqdm(chunks, desc="Cleaning & Embedding Chunks", unit="chunk"):
        chunk_id = str(uuid.uuid4())
        
        # 1. Clean the text of UI noise
        raw_text = chunk.text
        clean_content = clean_text(raw_text)
        
        # If the chunk was ONLY "Suggest an Edit", skip it entirely
        if not clean_content:
            continue

        # 2. Extract Explicit Page Context
        page_anchor = extract_page_header(chunk)
        
        # --- Image/Table Extraction ---
        image_filename = None
        if chunk.meta.doc_items:
            for item in chunk.meta.doc_items:
                if hasattr(item, "image") and item.image is not None:
                    image_filename = f"item_{chunk_id}.png"
                    image_path = os.path.join(IMAGE_DIR, image_filename)
                    item.image.pil_image.save(image_path, format="PNG")
                    break 

        page_start = chunk.meta.doc_items[0].prov[0].page_no if chunk.meta.doc_items and chunk.meta.doc_items[0].prov else 0
        page_end = chunk.meta.doc_items[-1].prov[0].page_no if chunk.meta.doc_items and chunk.meta.doc_items[-1].prov else 0

        # 3. Contextual Embedding Formulation
        # We explicitly lock the text to the page anchor so the vector space organizes perfectly
        embedding_input = f"[{page_anchor}] {clean_content}"
        embedding = model.encode(embedding_input)
        embedding_blob = embedding.astype(np.float32).tobytes()

        # --- Database Insertion ---
        cursor.execute("""
            INSERT INTO chunks (id, heading_context, text_content, page_start, page_end, image_filename, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            chunk_id,
            page_anchor,
            clean_content,
            page_start,
            page_end,
            image_filename,
            embedding_blob
        ))

    conn.commit()
    conn.close()
    
    print("\n--- Pipeline Complete ---")

if __name__ == "__main__":
    main()
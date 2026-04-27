import os
import sqlite3
import uuid
import re
import numpy as np
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions

# --- Configuration ---
PDF_PATH = "WhiteBook.pdf"
DB_PATH = "staffbook_kb.sqlite"
IMAGE_DIR = "ios_images"
MODEL_NAME = "Alibaba-NLP/gte-modernbert-base"

# Smaller chunks for highly specific medical dosing
CHUNK_SIZE_WORDS = 150
OVERLAP_WORDS = 40

def setup_database():
    """Initializes a fresh SQLite database for the iOS app."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
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
    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)

def scrub_noise(text: str) -> str:
    """
    Aggressively cleans MGH WhiteBook specific noise from the markdown.
    """
    # 1. Remove exact UI phrases
    ui_phrases = [
        "Submit Feedback", "Table of Contents", "Return to Table of Contents",
        "Suggest an Edit", "ACLS LOGISTICS & UPDATES"
    ]
    for phrase in ui_phrases:
        # Case insensitive replacement
        text = re.sub(f"(?i){phrase}", "", text)

    # 2. Strip standard Docling Image tags from the text
    text = re.sub(r"", "", text)
    
    # 3. Annihilate footers (Author Names and Page Numbers)
    text = re.sub(r"([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*\n*\s*\d{1,3}\s*$", "", text, flags=re.MULTILINE)
    
    # 4. Remove standalone page numbers sitting on their own line
    text = re.sub(r"^\s*\d{1,3}\s*$", "", text, flags=re.MULTILINE)

    # Clean up excessive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def extract_page_anchor(clean_md: str) -> str:
    """
    Extracts the top 3 meaningful lines of the page to create a robust, 
    highly-specific context anchor for all chunks on this page.
    """
    # Grab lines that have actual content, strip out Markdown hashes
    lines = [line.replace('#', '').strip() for line in clean_md.split('\n') if len(line.strip()) > 3]
    
    if not lines:
        return "General Medical Reference"
        
    # Join the top 3 lines to guarantee we capture overarching categories and sub-topics
    anchor_parts = lines[:3] 
    return " > ".join(anchor_parts)

def chunk_markdown(clean_md: str, page_num: int, page_anchor: str):
    """
    Slices the pristine markdown into overlapping, highly-dense context windows.
    """
    words = clean_md.split()
    chunks = []
    
    if not words:
        return chunks

    for i in range(0, len(words), CHUNK_SIZE_WORDS - OVERLAP_WORDS):
        chunk_words = words[i:i + CHUNK_SIZE_WORDS]
        chunk_text = " ".join(chunk_words)
        if len(chunk_text.strip()) > 20: # Ignore tiny fragments
            chunks.append({
                "id": str(uuid.uuid4()),
                "text": chunk_text,
                "page": page_num,
                "anchor": page_anchor
            })
        
        if i + CHUNK_SIZE_WORDS >= len(words):
            break
            
    return chunks

def main():
    print(f"Starting HARDENED ingestion pipeline for {PDF_PATH}...")
    setup_directories()
    conn = setup_database()
    cursor = conn.cursor()

    print(f"Loading {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)

    print("Configuring Docling for raw markdown extraction...")
    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_picture_images = True
    
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    print("Parsing document (this will take a moment)...")
    conv_result = converter.convert(PDF_PATH)
    doc = conv_result.document

    all_chunks = []

    # Iterate through the document page by page to ensure strict spatial grouping
    for page_no, page_elements in tqdm(doc.pages.items(), desc="Processing Pages"):
        
        # 1. Extract raw markdown for this specific page
        page_md = doc.export_to_markdown(page_no=page_no)
        
        # 2. Scrub the noise (footers, authors, buttons)
        clean_md = scrub_noise(page_md)
        
        if not clean_md:
            continue

        # 3. Establish the robust Page Anchor
        page_anchor = extract_page_anchor(clean_md)

        # 4. Dense Chunking
        page_chunks = chunk_markdown(clean_md, page_no, page_anchor)
        
        # 5. Assign Image Flag
        image_filename = f"page_{page_no}.png"
        
        for chunk in page_chunks:
            chunk['image'] = image_filename
            all_chunks.append(chunk)

    print(f"Generated {len(all_chunks)} highly-dense chunks. Embedding...")

    for chunk in tqdm(all_chunks, desc="Embedding Chunks"):
        # The Anchor is prepended to ensure the vector space groups by medical category
        embedding_input = f"[{chunk['anchor']}] {chunk['text']}"
        embedding = model.encode(embedding_input)
        embedding_blob = embedding.astype(np.float32).tobytes()

        cursor.execute("""
            INSERT INTO chunks (id, heading_context, text_content, page_start, page_end, image_filename, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            chunk["id"],
            chunk["anchor"],
            chunk["text"],
            chunk["page"],
            chunk["page"],
            chunk["image"],
            embedding_blob
        ))

    conn.commit()
    conn.close()
    
    print("\n--- Pipeline Complete ---")

if __name__ == "__main__":
    main()
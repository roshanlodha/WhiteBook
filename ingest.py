import os
import sqlite3
import uuid
import base64
import json
import numpy as np
from tqdm import tqdm
from pathlib import Path
from pdf2image import convert_from_path
from sentence_transformers import SentenceTransformer
from openai import OpenAI
from dotenv import load_dotenv

# --- Configuration Setup ---
load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL_NAME")
EMBED_MODEL = os.getenv("EMBEDDING_MODEL_NAME")
PDF_PATH = os.getenv("PDF_PATH")
DB_PATH = os.getenv("DB_PATH")
IMAGE_DIR = os.getenv("IMAGE_DIR")

BATCH_FILE = "batch_requests.jsonl"
STATE_FILE = "batch_state.json"

if not all([API_KEY, OPENAI_MODEL, EMBED_MODEL, PDF_PATH, DB_PATH, IMAGE_DIR]):
    raise ValueError("Missing one or more required environment variables in the .env file.")

client = OpenAI(api_key=API_KEY)

# --- State Management ---
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return None

def save_state(state_data):
    with open(STATE_FILE, "w") as f:
        json.dump(state_data, f)

def clear_state():
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    if os.path.exists(BATCH_FILE):
        os.remove(BATCH_FILE)

# --- Database & Encoding ---
def setup_database():
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

def encode_image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def build_batch_request(page_no: int, base64_image: str) -> dict:
    # --- UPGRADED MULTIMODAL PROMPT ---
    prompt = """
    You are an expert medical data extractor. Analyze this page from a medical manual.
    
    1. Identify the overarching topic of the page (e.g., "Cardiology > ACLS Tachycardia").
    2. Extract ALL clinical data, including tables, flowcharts, lists, AND purely visual diagrams (e.g., anatomical patch placements, device interfaces, EKG strips).
    3. Convert every row of a table, branch of a flowchart, or visual diagram into a HIGHLY DENSE, SELF-CONTAINED paragraph.
    4. If there is a visual illustration (like defibrillator pad placement or a device monitor), write a highly descriptive paragraph explaining exactly what it shows spatially and functionally so a reader who cannot see the image understands it perfectly.
    
    CRITICAL RULE: Never use pronouns or generic terms. Always restate the disease, drug name, or procedure in every paragraph. 
    Ignore page numbers, author names, and UI buttons like 'Suggest an Edit'.
    """

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "page_extraction",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "page_topic_anchor": {"type": "string"},
                    "self_contained_chunks": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "required": ["page_topic_anchor", "self_contained_chunks"],
                "additionalProperties": False
            }
        }
    }

    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ],
        "response_format": response_format
    }

    return {
        "custom_id": f"page_{page_no}",
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": body
    }

# --- Core Logic ---
def main():
    setup_directories()
    state = load_state()

    # PHASE 1: Build and Submit Batch
    if not state:
        print(f"--- Phase 1: Initiating Batch Submission for {PDF_PATH} ---")
        print("1. Converting PDF to OPTIMIZED images and building batch file...")
        
        pages = convert_from_path(PDF_PATH, dpi=150)
        
        with open(BATCH_FILE, "w") as f:
            for page_no, page_image in enumerate(tqdm(pages, desc="Encoding Pages"), start=1):
                image_filename = f"page_{page_no}.jpg"
                image_path = os.path.join(IMAGE_DIR, image_filename)
                
                page_image.save(image_path, "JPEG", optimize=True, quality=85)
                
                base64_img = encode_image_to_base64(image_path)
                req = build_batch_request(page_no, base64_img)
                f.write(json.dumps(req) + "\n")

        print("2. Uploading JSONL to OpenAI...")
        batch_input_file = client.files.create(
            file=open(BATCH_FILE, "rb"),
            purpose="batch"
        )

        print("3. Creating Batch Job...")
        batch = client.batches.create(
            input_file_id=batch_input_file.id,
            endpoint="/v1/chat/completions",
            completion_window="24h"
        )
        
        save_state({"batch_id": batch.id})
        
        print(f"\n✅ Batch successfully submitted! (ID: {batch.id})")
        print("Run this script again later to check the status.\n")
        return

    # PHASE 2 & 3: Check Status and Process Results
    batch_id = state["batch_id"]
    print(f"--- Phase 2: Checking Existing Batch (ID: {batch_id}) ---")
    
    batch_status = client.batches.retrieve(batch_id)
    status = batch_status.status

    if status in ["validating", "in_progress", "finalizing"]:
        print(f"⏳ Batch is still processing. Current status: '{status}'.")
        print("Run the script again later.\n")
        return
        
    if status in ["failed", "cancelled", "expired"]:
        print(f"\n❌ Batch job ended with status: {status}")
        
        if hasattr(batch_status, 'errors') and batch_status.errors:
            print("\n--- ERROR DETAILS ---")
            for error in batch_status.errors.data:
                line_info = f"(Line {error.line})" if getattr(error, 'line', None) else ""
                print(f"[{error.code}] {error.message} {line_info}")
            print("---------------------\n")
            
        print("Clearing state file so you can fix the issue and try again.")
        clear_state()
        return

    if status == "completed":
        print("\n✅ Batch completed! Downloading results...")
        output_file_id = batch_status.output_file_id
        
        if batch_status.error_file_id:
            print("⚠️ Some individual requests failed. Check the OpenAI dashboard for the error file.")

        result_content = client.files.content(output_file_id).text

        print("\n--- Phase 3: Embedding and Database Insertion ---")
        print("Loading Embedding Model...")
        model = SentenceTransformer(EMBED_MODEL, trust_remote_code=True)
        conn = setup_database()
        cursor = conn.cursor()

        all_chunks = []

        for line in result_content.strip().split('\n'):
            res = json.loads(line)
            custom_id = res['custom_id']
            page_no = int(custom_id.split('_')[1])
            
            if res['response']['status_code'] != 200:
                print(f"Warning: Page {page_no} failed to generate. Skipping.")
                continue
                
            content_str = res['response']['body']['choices'][0]['message']['content']
            
            try:
                extraction = json.loads(content_str)
                anchor = extraction.get('page_topic_anchor', 'General Medical Reference')
                for text_chunk in extraction.get('self_contained_chunks', []):
                    if len(text_chunk.strip()) > 20:
                        all_chunks.append({
                            "id": str(uuid.uuid4()),
                            "text": text_chunk,
                            "page": page_no,
                            "anchor": anchor,
                            "image": f"page_{page_no}.jpg" 
                        })
            except json.JSONDecodeError:
                print(f"Warning: Page {page_no} returned malformed JSON. Skipping.")

        print(f"Generated {len(all_chunks)} chunks. Embedding into SQLite...")
        
        for chunk in tqdm(all_chunks, desc="Embedding"):
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
        
        print("\n🧹 Cleaning up temporary state files...")
        clear_state()
            
        print("\n🎉 Pipeline Complete! Your database is fully populated and ready for iOS.")

if __name__ == "__main__":
    main()
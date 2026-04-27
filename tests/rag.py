import os
import sqlite3
import numpy as np
import sys
from pathlib import Path
from sentence_transformers import SentenceTransformer
from llama_cpp import Llama

# --- Configuration ---
ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "staffbook_kb.sqlite"
LLM_PATH = ROOT_DIR / "Qwen3-8B-Q4_K_M.gguf" # Update this to match your exact Qwen3 downloaded filename
EMBED_MODEL = "Alibaba-NLP/gte-modernbert-base"

# ANSI Colors for UI
ORANGE = "\033[38;5;214m"
CYAN = "\033[96m"
BOLD = "\033[1m"
ITALIC = "\033[3m"
RESET = "\033[0m"

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def retrieve_context(query, embedder, cursor, top_k=3):
    query_vec = embedder.encode(query).astype(np.float32)
    cursor.execute("SELECT id, heading_context, text_content, page_start, image_filename, embedding FROM chunks")
    rows = cursor.fetchall()
    
    results = []
    for row in rows:
        chunk_id, heading, text, page, img, blob = row
        db_vec = np.frombuffer(blob, dtype=np.float32)
        score = cosine_similarity(query_vec, db_vec)
        results.append({
            "score": score,
            "heading": heading,
            "text": text,
            "page": page,
            "image": img
        })
        
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]

def build_system_prompt():
    # By default Qwen3 enables thinking if prompted or if using standard chat templates.
    # We explicitly tell it to use the context and to show its work.
    return (
        "You are an elite emergency medicine assistant. "
        "Answer the clinical query strictly using ONLY the provided context chunks. "
        "Do not use outside knowledge. If the answer is not in the context, say you don't know. "
        "If the context relies on a visual diagram, explicitly state the user should reference the attached image."
    )

def main():
    print(f"{BOLD}{ORANGE}=== Staffbook Qwen3 RAG Terminal ==={RESET}")
    
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}. Run ingestion first.")
        return
    if not LLM_PATH.exists():
        print(f"Error: LLM not found at {LLM_PATH}.")
        return

    print(f"Loading Retriever ({EMBED_MODEL})...")
    embedder = SentenceTransformer(EMBED_MODEL, trust_remote_code=True)
    
    print(f"Loading Generator ({LLM_PATH.name}) with Metal GPU support...")
    llm = Llama(
        model_path=str(LLM_PATH),
        n_gpu_layers=-1, 
        n_ctx=4096,      
        verbose=False    
    )
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"{BOLD}{CYAN}Ready. Type your medical query below. Type 'exit' or 'quit' to stop.{RESET}\n")

    while True:
        try:
            query = input(f"{BOLD}{CYAN}Query > {RESET}")
            if query.lower() in ['exit', 'quit']:
                break
            if not query.strip():
                continue
                
            # --- RETRIEVAL ---
            top_chunks = retrieve_context(query, embedder, cursor, top_k=3)
            
            print(f"\n{BOLD}--- Retrieved Context ---{RESET}")
            context_string = ""
            for i, chunk in enumerate(top_chunks, 1):
                img_tag = f" [IMAGE: {chunk['image']}]" if chunk['image'] else ""
                print(f"{ORANGE}{i}. [{chunk['heading']}] (Page {chunk['page']}, Score: {chunk['score']:.3f}){img_tag}{RESET}")
                context_string += f"--- Chunk {i} ---\nSection: {chunk['heading']}\nText: {chunk['text']}\nAssociated Image: {chunk['image'] or 'None'}\n\n"
                
            # --- SYNTHESIS ---
            print(f"\n{BOLD}--- Qwen3 Synthesis ---{RESET}")
            
            # We add a trigger to force Qwen3 into thinking mode for complex queries
            messages = [
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": f"Context:\n{context_string}\n\nQuestion: {query}\n\n/think"}
            ]
            
            stream = llm.create_chat_completion(
                messages=messages,
                stream=True,
                temperature=0.6,          # Alibaba's Qwen3 recommended temp
                top_p=0.95,               # Alibaba's Qwen3 recommended top_p
                presence_penalty=1.5,     # HIGHLY recommended by Alibaba for Qwen3 to prevent looping
                max_tokens=1024
            )
            
            in_think_block = False
            
            # Simple state machine to colorize the <think> tags in real-time
            for chunk in stream:
                delta = chunk['choices'][0]['delta']
                if 'content' in delta:
                    text = delta['content']
                    
                    if "<think>" in text:
                        in_think_block = True
                        text = text.replace("<think>", f"{ITALIC}{ORANGE}<think>\n")
                    
                    if "</think>" in text:
                        in_think_block = False
                        text = text.replace("</think>", f"\n</think>{RESET}{CYAN}")
                    
                    if in_think_block and text.strip() and not "<think>" in text:
                        # Ensure text stays orange if it comes in chunks
                        sys.stdout.write(f"{ORANGE}{text}")
                    else:
                        sys.stdout.write(f"{CYAN if not in_think_block else ''}{text}")
                        
                    sys.stdout.flush()
            
            print(f"{RESET}\n")
            print("-" * 60)
            
        except KeyboardInterrupt:
            print("\nExiting...")
            break

    conn.close()

if __name__ == "__main__":
    main()
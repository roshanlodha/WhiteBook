import sqlite3
from pathlib import Path

# Resolve the path to the database (assuming script is in /tests and DB is in root)
ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "staffbook_kb.sqlite"

def run_sanity_check():
    print("========================================")
    print("🩺 Staffbook Database Sanity Check")
    print("========================================")
    
    if not DB_PATH.exists():
        print(f"❌ Error: Database not found at {DB_PATH}.")
        print("Make sure you have run the main ingestion script first.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # --- Test 1: High-Level Stats ---
    cursor.execute("SELECT COUNT(*) FROM chunks")
    total_chunks = cursor.fetchone()[0]
    print(f"✅ Total chunks ingested: {total_chunks}\n")

    # --- Test 2: The Layout & Context Anchor Test ---
    # We specifically look for "Procainamide" to see how Docling handled the column flattening
    search_term = "%procainamide%"
    print(f"🔍 Searching for '{search_term.replace('%', '')}' to verify structural extraction...")
    
    cursor.execute("""
        SELECT heading_context, text_content, page_start, image_filename 
        FROM chunks 
        WHERE text_content LIKE ? COLLATE NOCASE
        LIMIT 3
    """, (search_term,))
    
    results = cursor.fetchall()

    if not results:
        print("⚠️ No chunks found containing that term.")
    else:
        for idx, row in enumerate(results, start=1):
            context, text, page, img = row
            print(f"\n--- Chunk {idx} ---")
            print(f"📌 Context Anchor : {context}")
            print(f"📄 Page Number    : {page}")
            print(f"🖼️ Linked Image   : {img if img else 'None'}")
            print(f"📝 Text Content   :\n{'-'*40}\n{text}\n{'-'*40}")

    # --- Test 3: The UI Noise Banlist Test ---
    print("\n🧹 Verifying Noise Cancellation...")
    cursor.execute("""
        SELECT COUNT(*) FROM chunks 
        WHERE text_content LIKE '%Suggest an Edit%' 
           OR text_content LIKE '%Table of Contents%'
    """)
    noise_count = cursor.fetchone()[0]
    
    if noise_count == 0:
        print("✅ Perfect! Zero banned UI strings found in the text corpus.")
    else:
        print(f"❌ Warning: Found {noise_count} chunks still containing UI noise.")

    conn.close()
    print("\n========================================")
    print("Sanity Check Complete.")
    print("========================================")

if __name__ == "__main__":
    run_sanity_check()
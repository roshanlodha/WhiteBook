import sqlite3
from pathlib import Path

# Adjust path if your DB is located elsewhere
DB_PATH = Path(__file__).resolve().parent.parent / "staffbook_kb.sqlite"

def main():
    print("🔍 Staffbook Database Spot-Check")
    print("--------------------------------------------------")
    
    if not DB_PATH.exists():
        print(f"❌ Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Search for chunks containing the word "procainamide"
    search_term = "%procainamide%"
    
    cursor.execute("""
        SELECT page_start, heading_context, text_content 
        FROM chunks 
        WHERE text_content LIKE ? COLLATE NOCASE
        ORDER BY page_start ASC
    """, (search_term,))
    
    results = cursor.fetchall()

    if not results:
        print("⚠️ No chunks found containing 'procainamide'.")
    else:
        print(f"✅ Found {len(results)} chunks containing the search term:\n")
        
        for idx, (page, anchor, text) in enumerate(results, 1):
            print(f"--- Result {idx} ---")
            print(f"📄 Page   : {page}")
            print(f"⚓ Anchor : {anchor}")
            
            # Print a preview of the text, highlighting if ACLS is missing
            has_acls = "ACLS" in text.upper() or "ACLS" in anchor.upper()
            print(f"🎯 ACLS Context Present? : {'YES' if has_acls else 'NO (This is why it failed!)'}")
            
            print(f"📝 Text Preview:\n{text[:200]}...\n")

    conn.close()

if __name__ == "__main__":
    main()
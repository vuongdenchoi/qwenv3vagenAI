import sys
from pathlib import Path

# Windows console encoding fix
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Thêm backend vào sys.path để import dễ dàng
sys.path.append(str(Path(__file__).resolve().parent))

from agents.retrieval_agent import RetrievalAgent

def test():
    print("[TEST] Khởi tạo RetrievalAgent...")
    retriever = RetrievalAgent(top_k=5)
    
    queries = [
        "màu tương phản",
        "typography readable layout",
        "logo exclusion zone"
    ]
    
    for q in queries:
        print(f"\n=======================================================")
        print(f"🔍 TESTING QUERY: '{q}'")
        print(f"=======================================================")
        results = retriever.retrieve(q)
        for idx, r in enumerate(results):
            print(f"  {idx+1}. [{r['category'].upper()} > {r['section']}] Rule {r['rule_number']} — {r['rule_title']}")
            print(f"     [Dense Cosine]: {r['score']:.4f} | [Sparse BM25]: {r['sparse_score']:.4f} | [Fused RRF]: {r['rrf_score']:.4f}")
            snippet = r['text'].replace('\n', ' ')[:100]
            print(f"     [Snippet]: {snippet}...")

if __name__ == "__main__":
    test()

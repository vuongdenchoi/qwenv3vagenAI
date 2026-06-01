"""
Retrieval Agent – tìm design rules liên quan dùng Multilingual Embedding.
Model: paraphrase-multilingual-MiniLM-L12-v2
  - Hỗ trợ tiếng Việt + tiếng Anh (và 50+ ngôn ngữ khác)
  - Không cần query expansion / synonym dict
  - Category boost ×1.3 vẫn giữ nguyên
"""
import os
os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"

import json
import re
import numpy as np
from typing import List, Dict, Set, Tuple
from pathlib import Path
from rank_bm25 import BM25Okapi


INDEX_DIR  = Path(__file__).resolve().parent.parent / "knowledge_base" / "faiss_index"
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Map query keywords → category names (dùng để boost score)
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "color_theory"  : ["color", "colour", "hue", "saturation", "contrast", "palette",
                        "rgb", "cmyk", "tint", "shade", "complementary", "analogous",
                        "warm", "cool", "vibration", "value",
                        # Vietnamese
                        "màu", "màu sắc", "tương phản", "bảng màu", "độ bão hòa"],
    "typography"    : ["typography", "typeface", "font", "serif", "sans", "type",
                        "leading", "kerning", "tracking", "legibility", "readability",
                        "headline", "body text", "letter", "glyph", "weight",
                        # Vietnamese
                        "chữ", "font chữ", "kiểu chữ", "cỡ chữ", "dễ đọc"],
    "layout_rules"  : ["layout", "grid", "composition", "margin", "spacing", "alignment",
                        "column", "proximity", "whitespace", "white space", "hierarchy",
                        "balance", "symmetry", "asymmetry", "direction", "wayfinding",
                        # Vietnamese
                        "bố cục", "lưới", "khoảng trắng", "căn chỉnh", "cân bằng"],
    "logo_design"   : ["logo", "logotype", "brand", "identity", "mark", "monogram",
                        "wordmark", "branding", "graphic identity", "exclusion zone",
                        # Vietnamese
                        "thương hiệu", "nhận diện"],
    "poster_design" : ["poster", "advertisement", "billboard", "campaign", "print",
                        "focal", "visual noise", "outdoor", "format", "signage",
                        # Vietnamese
                        "áp phích", "quảng cáo", "tờ rơi"],
    "icon_design"   : ["icon", "pictogram", "symbol", "wayfinding", "glyph",
                        "ui icon", "sign", "pictograph", "stroke weight", "icon set",
                        "icon system", "monochrome icon", "icon grid", "legibility",
                        "icon style", "navigation icon", "app icon", "ui symbol",
                        # Vietnamese
                        "biểu tượng", "icon"],
    "pattern_design": ["pattern", "motif", "repeat", "tile", "tiling", "textile",
                        "half-drop", "brick repeat", "mirrored repeat", "tossed",
                        "surface design", "print design", "seamless", "density",
                        "ditsy", "floral pattern", "geometric pattern", "folk pattern",
                        # Vietnamese
                        "họa tiết", "hoa văn", "lặp lại"],
}

CATEGORY_BOOST = 1.3  # score multiplier when query matches a category


def tokenize(text: str) -> List[str]:
    """Simple tokenizer for BM25 keyword matching."""
    return re.findall(r'\b\w+\b', text.lower())


def rrf(dense_ranks: np.ndarray, sparse_ranks: np.ndarray, k_rrf: int = 60) -> Dict[int, float]:
    """Reciprocal Rank Fusion (RRF) algorithm to combine dense and sparse rankings."""
    scores = {}
    for rank, idx in enumerate(dense_ranks):
        scores[idx] = scores.get(idx, 0.0) + 1.0 / (k_rrf + rank + 1)
    for rank, idx in enumerate(sparse_ranks):
        scores[idx] = scores.get(idx, 0.0) + 1.0 / (k_rrf + rank + 1)
    return scores


class RetrievalAgent:
    def __init__(self, top_k: int = 10):
        self.top_k = top_k
        self._load_model()
        self._load_index()

    def _load_model(self):
        """Load sentence-transformer model (1 lần khi khởi tạo)."""
        from sentence_transformers import SentenceTransformer
        print(f"[RetrievalAgent] Loading embedding model: {MODEL_NAME}")
        self.model = SentenceTransformer(MODEL_NAME)
        print(f"[RetrievalAgent] Model loaded.")

    def _load_index(self):
        """Load embedding vectors và metadata từ disk, đồng thời khởi tạo BM25."""
        emb_path  = INDEX_DIR / "embeddings.npy"
        meta_path = INDEX_DIR / "metadata.json"

        if not emb_path.exists():
            raise FileNotFoundError(
                f"Embedding index không tìm thấy tại {INDEX_DIR}. "
                "Chạy backend/knowledge_base/build_index.py trước."
            )

        self.embeddings = np.load(str(emb_path))  # shape (N, 384)
        with open(meta_path, encoding="utf-8") as f:
            self.metadata = json.load(f)
        print(f"[RetrievalAgent] Loaded embeddings: {self.embeddings.shape[0]} chunks, dim={self.embeddings.shape[1]}")

        # Khởi tạo động BM25 từ tokens trong metadata (cực nhanh và an toàn hơn Pickle)
        corpus_tokens = []
        for entry in self.metadata:
            tokens = entry.get("tokens")
            if tokens is None:
                tokens = tokenize(entry.get("text", ""))
                entry["tokens"] = tokens
            corpus_tokens.append(tokens)
        
        self.bm25 = BM25Okapi(corpus_tokens)
        print(f"[RetrievalAgent] BM25 Index initialized with {len(corpus_tokens)} documents.")

    # ------------------------------------------------------------------
    # Detect which design categories the query matches (for boost)
    # ------------------------------------------------------------------
    def _detect_categories(self, query: str) -> Set[str]:
        q = query.lower()
        matched = set()
        for cat, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in q for kw in keywords):
                matched.add(cat)
        return matched

    # ------------------------------------------------------------------
    # Main retrieval (Hybrid Search)
    # ------------------------------------------------------------------
    def retrieve(self, query: str) -> list:
        """Return top-k relevant rules using Hybrid Search (Dense MiniLM + Sparse BM25) and RRF.
        
        Hỗ trợ tiếng Việt + tiếng Anh với model paraphrase-multilingual-MiniLM-L12-v2.
        """
        from sklearn.metrics.pairwise import cosine_similarity

        # --- 1. Dense Search ---
        query_vec = self.model.encode([query])  # shape (1, 768)
        dense_scores = cosine_similarity(query_vec, self.embeddings).flatten()
        dense_ranks = np.argsort(dense_scores)[::-1]

        # --- 2. Sparse Search (BM25) ---
        query_tokens = tokenize(query)
        sparse_scores = self.bm25.get_scores(query_tokens)
        sparse_ranks = np.argsort(sparse_scores)[::-1]

        # --- 3. Reciprocal Rank Fusion (RRF) ---
        rrf_scores = rrf(dense_ranks, sparse_ranks, k_rrf=60)

        # --- 4. Apply Category Boost on RRF Scores ---
        boosted_categories = self._detect_categories(query)
        final_scores = {}
        for idx, rrf_score in rrf_scores.items():
            entry = self.metadata[idx]
            score = rrf_score
            if entry.get("category") in boosted_categories:
                score *= CATEGORY_BOOST
            final_scores[idx] = score

        # Sắp xếp theo điểm số RRF đã được boost
        top_indices = sorted(final_scores.keys(), key=lambda x: final_scores[x], reverse=True)[:self.top_k]

        print(f"[RetrievalAgent] Query: '{query[:60]}'")
        if boosted_categories:
            print(f"[RetrievalAgent] Boosting categories: {boosted_categories}")

        results = []
        for idx in top_indices:
            entry = self.metadata[idx].copy()
            entry["score"]       = float(dense_scores[idx]) # Giữ dense score làm chuẩn tương thích
            entry["sparse_score"] = float(sparse_scores[idx])
            entry["rrf_score"]    = float(final_scores[idx])
            entry["rule_number"] = entry.get("rule_number", 0)
            entry["section"]     = entry.get("section", "General")
            entry["rule_title"]  = entry.get("rule_title", "")
            results.append(entry)
        return results

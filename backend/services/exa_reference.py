import os
import json
import hashlib
import requests
from dotenv import load_dotenv

# Try loading from standard paths
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

EXA_API_KEY = os.getenv('EXA_API_KEY')
CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', 'data_original', 'ref_cache.json')

def build_reference(issue_description: str):
    if not EXA_API_KEY:
        print("[Exa API] EXA_API_KEY not configured.")
        return None
    try:
        url = "https://api.exa.ai/search"
        headers = {
            "x-api-key": EXA_API_KEY,
            "Content-Type": "application/json"
        }
        
        # Truy vấn kết hợp ngữ cảnh thiết kế để ưu tiên ra ảnh minh họa (Pinterest, Dribbble, Behance, báo chí...)
        search_query = f"{issue_description} graphic design example inspiration"
        
        payload = {
            "query": search_query,
            "type": "auto",
            "numResults": 10,
            "contents": {"text": False}
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        results = data.get("results", [])
        
        # Ưu tiên trả về kết quả có chứa ảnh (Visual Reference)
        for r in results:
            if r.get("image"):
                return {
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "image_url": r.get("image")
                }
                
        # Fallback nếu không có ảnh nào được tìm thấy
        if results:
            top = results[0]
            return {
                "title": top.get("title"),
                "url": top.get("url"),
                "image_url": None
            }
            
        return None
    except Exception as e:
        print(f"[Exa API] Search failed: {e}")
        return None

def get_cached_or_search(category: str, rule_violated: str, issue_description: str):
    # Normalize key based on category and rule_violated
    base_str = f"{category} | {rule_violated}".strip().lower()
    issue_key = hashlib.md5(base_str.encode('utf-8')).hexdigest()
    
    # Check cache
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        except Exception:
            cache = {}
            
    if issue_key in cache:
        print(f"[Exa API] Cache hit for key: {base_str}")
        return cache[issue_key]
        
    print(f"[Exa API] Cache miss for key: {base_str}. Searching...")
    ref = build_reference(issue_description)
    if ref:
        cache[issue_key] = ref
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            with open(CACHE_FILE, "w", encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Exa API] Could not save cache: {e}")
            
    return ref

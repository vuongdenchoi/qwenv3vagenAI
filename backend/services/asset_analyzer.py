import os
import json
import requests
import asyncio

ASSET_SYSTEM = """You are a brand consistency auditor.
Compare design assets against a brand DNA profile.
Always respond with valid JSON only. No preamble, no markdown."""

def build_asset_prompt(dna: dict, filename: str) -> str:
    return f"""
BRAND DNA PROFILE:
{json.dumps(dna, indent=2)}

Analyze this design asset for brand consistency deviations compared to the above BRAND DNA PROFILE.
Return ONLY this JSON:

{{
  "asset_id": "{filename}",
  "brand_score": <0-100>,
  "severity": "ok|minor|moderate|severe",
  "issues": [
    {{
      "category": "color|typography|layout|image_mood|cta|logo|spacing",
      "description": "Mô tả lỗi cụ thể bằng tiếng Việt",
      "severity": "minor|moderate|severe",
      "suggestion": "Gợi ý sửa cụ thể bằng tiếng Việt"
    }}
  ]
}}

Rules:
- brand_score: 90-100 = ok, 70-89 = minor, 50-69 = moderate, <50 = severe
- If no issues found, return empty issues array and severity "ok"
- Max 5 issues per asset
"""

def analyze_asset(dna: dict, image_b64: str, filename: str) -> dict:
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise Exception("Missing DASHSCOPE_API_KEY")

    payload = {
        "model": "qwen-vl-max",
        "messages": [
            {"role": "system", "content": ASSET_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    {"type": "text", "text": build_asset_prompt(dna, filename)}
                ]
            }
        ],
        "max_tokens": 1500
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    resp = requests.post("https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions", headers=headers, json=payload, timeout=90)
    if resp.ok:
        data = resp.json()
        raw = data["choices"][0]["message"]["content"].strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.lower().startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    else:
        raise Exception(f"API Error: {resp.text}")

async def analyze_batch(dna: dict, assets: list) -> list:
    """Parallel analysis với concurrency limit = 3"""
    semaphore = asyncio.Semaphore(3)
    loop = asyncio.get_event_loop()
    
    async def analyze_one(img_b64, filename):
        async with semaphore:
            # We wrap the synchronous request in run_in_executor to avoid blocking (compatible with Python < 3.9)
            return await loop.run_in_executor(None, analyze_asset, dna, img_b64, filename)
    
    tasks = [analyze_one(img, name) for img, name in assets]
    return await asyncio.gather(*tasks)

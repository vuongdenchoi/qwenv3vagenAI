import os
import json
import requests

DNA_SYSTEM = """You are a brand identity analyst. 
Analyze design assets and extract brand DNA patterns.
Always respond with valid JSON only. No preamble, no markdown."""

DNA_PROMPT = """
Analyze these reference brand assets and extract the Visual DNA profile.
Return ONLY this JSON structure:

{
  "main_colors": ["#hex1", "#hex2", "#hex3"],
  "color_mood": "warm|cool|neutral|vibrant|dark|pastel",
  "background_treatment": "solid|gradient|textured|white|dark",
  "typography_style": "serif|sans-serif|display|script|mixed",
  "font_weight_pattern": "light|regular|bold|heavy|mixed",
  "layout_pattern": "centered|asymmetric|grid|editorial|minimal",
  "visual_density": "sparse|balanced|dense",
  "image_mood": "minimal|bold|lifestyle|corporate|playful|luxe",
  "cta_style": "filled-button|outlined|text-link|none|mixed",
  "logo_placement": "top-left|top-center|bottom|none-detected",
  "overall_tone": "playful|professional|luxe|casual|bold|minimal"
}
"""

def extract_dna(ref_image_b64_list: list) -> dict:
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise Exception("Missing DASHSCOPE_API_KEY")
        
    content = []
    for img_b64 in ref_image_b64_list:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
        })
    content.append({"type": "text", "text": DNA_PROMPT})

    payload = {
        "model": "qwen-vl-max",
        "messages": [
            {"role": "system", "content": DNA_SYSTEM},
            {"role": "user", "content": content}
        ],
        "max_tokens": 1000
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

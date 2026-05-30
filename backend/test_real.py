import sys
from pathlib import Path
import json

sys.path.append(str(Path(__file__).resolve().parent))

from agents.post_process_agent import PostProcessAgent

def run_test():
    # Load raw result (we can mock it with the raw data returned by Qwen)
    raw_result = {
        "compliments": ["Test"],
        "e": [
            {
                "r": "The background features large, semi-transparent Chinese characters that blend into the figure’s blue hair and clothing, creating severe figure-ground confusion <box>(0,80),(998,750)</box>",
                "issue": "Test",
                "suggestion": "Test",
                "s": "critical",
                "g": "poster_design"
            }
        ]
    }
    
    import io
    from PIL import Image
    img = Image.new("RGB", (832, 1248))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    image_bytes = buf.getvalue()
    
    post_proc = PostProcessAgent()
    res = post_proc.process(raw_result, image_bytes)
    print("PROCESSED RESULT:", res["e"][0]["c"])

if __name__ == "__main__":
    run_test()

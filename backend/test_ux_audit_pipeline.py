import os
import sys
from pathlib import Path
from PIL import Image
import io

# Load environment variables from .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
except ImportError:
    pass

# Fix Windows console encoding issues when outputting Vietnamese
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Patch requests and ssl to bypass SSL verification globally (disabled as it breaks on this system)
# import ssl
# import requests
# try:
#     _original_create_default_context = ssl.create_default_context
#     def _patched_create_default_context(*args, **kwargs):
#         context = _original_create_default_context(*args, **kwargs)
#         context.check_hostname = False
#         context.verify_mode = ssl.CERT_NONE
#         return context
#     ssl.create_default_context = _patched_create_default_context
#     ssl._create_default_https_context = ssl._create_unverified_context
#     
#     _original_request = requests.Session.request
#     def _patched_request(self, method, url, *args, **kwargs):
#         kwargs['verify'] = False
#         return _original_request(self, method, url, *args, **kwargs)
#     requests.Session.request = _patched_request
#     
#     # Patch urllib3 to bypass SSL verification globally
#     import urllib3.util.ssl_
#     urllib3.util.ssl_.create_urllib3_context = lambda *args, **kwargs: ssl._create_unverified_context()
# except Exception as e:
#     print(f"[WARNING] Failed to patch SSL: {e}")

# Setup path
sys.path.append(str(Path(__file__).parent))

from agents.design_check_agent import DesignCheckAgent

def main():
    print("==========================================================")
    print("   TESTING HYBRID MULTI-AGENT UX AUDIT PIPELINE")
    print("==========================================================")
    
    # Check API key
    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("[WARNING] DASHSCOPE_API_KEY is not set. LLM Critic will fallback to mock summary.")
    else:
        print("[OK] DASHSCOPE_API_KEY is set.")

    # Load test image
    image_path = Path(__file__).parent / "latest_result.png"
    if not image_path.exists():
        print(f"[INFO] latest_result.png not found. Creating a mock UI image for test...")
        # Create a mock blue UI image with some white text elements
        img = Image.new("RGB", (800, 600), color=(15, 23, 42)) # Dark slate
        # Let's save it
        image_bytes_io = io.BytesIO()
        img.save(image_bytes_io, format="PNG")
        image_bytes = image_bytes_io.getvalue()
    else:
        print(f"[OK] Loading existing test image: {image_path}")
        with open(image_path, "rb") as f:
            image_bytes = f.read()

    # Initialize DesignCheckAgent
    print("\n[Step 1] Initializing DesignCheckAgent (tải các mô hình local)...")
    try:
        agent = DesignCheckAgent(api_key=api_key)
        print("[OK] Agent initialized.")
    except Exception as e:
        print(f"[ERROR] Failed to initialize agent: {e}")
        return

    # Execute UX Audit
    print("\n[Step 2] Running run_ux_audit()...")
    print("  * Tầng 1: Chạy Florence-2 và OWL-ViT cục bộ trên CPU...")
    print("  * Tầng 2: Kiểm tra Alignment, Spacing, Contrast...")
    print("  * Tầng 3: LLM Critic phân tích và viết gợi ý...")
    print("Vui lòng đợi (quá trình này mất khoảng 20-40s trên CPU)...")
    
    mock_persona = {
        "schemaVersion": 1,
        "designPatterns": {
            "recentAnalysisCount": 2,
            "topIssueCategories": ["typography", "color_theory"],
            "severityMix": {"critical": 1, "major": 2},
            "focusHints": ["major typography", "critical color_theory"]
        },
        "behavior": {
            "primaryWorkflow": "ANALYZE"
        }
    }
    try:
        result = agent.run_ux_audit(image_bytes, lang="vi", persona_context=mock_persona)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ERROR] Pipeline execution failed: {e}")
        return

    print("\n==========================================================")
    print("   UX AUDIT PIPELINE RESULTS")
    print("==========================================================")
    print(f"Success: {result.get('success')}")
    print(f"Elements detected (Consensus): {len(result.get('detected_elements', []))}")
    for idx, el in enumerate(result.get('detected_elements', [])[:5]):
        print(f"  [{idx+1}] Label: {el['label']}, Box: {el['box_2d']}, Conf: {el['score']:.2f}")
    if len(result.get('detected_elements', [])) > 5:
        print(f"  ... và {len(result.get('detected_elements')) - 5} phần tử khác.")

    print(f"\nErrors found by Auditors: {len(result.get('errors', []))}")
    for idx, err in enumerate(result.get('errors', [])[:5]):
        print(f"  [{idx+1}] Severity: {err['s'].upper()}, Category: {err['g']}, Msg: {err['r'][:120]}...")
    if len(result.get('errors', [])) > 5:
        print(f"  ... và {len(result.get('errors')) - 5} lỗi khác.")

    print("\n[Critic Summary]")
    print(result.get("summary", "No summary generated."))

    print("\n[Markdown Report Length]")
    print(f"Report length: {len(result.get('markdown_report', ''))} characters")
    
    print("\n[OK] Test completed successfully!")

if __name__ == "__main__":
    main()

import ssl
import requests

# Save original create_default_context
_original_create_default_context = ssl.create_default_context

def _patched_create_default_context(*args, **kwargs):
    context = _original_create_default_context(*args, **kwargs)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context

ssl.create_default_context = _patched_create_default_context
ssl._create_default_https_context = ssl._create_unverified_context

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Try request
print("Making request to dashscope-intl.aliyuncs.com...")
try:
    resp = requests.post("https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation", json={}, timeout=5)
    print(f"Success! Status code: {resp.status_code}")
    print(f"Response: {resp.text[:200]}")
except Exception as e:
    print(f"Failed: {e}")

import sys
import os

backend_path = os.path.abspath('d:/WILLA/qwenv3vagenAI-main/backend')
sys.path.insert(0, backend_path)

from agents.florence_agent import FlorenceAgent

with open("d:/WILLA/qwenv3vagenAI-main/test.png", "rb") as f:
    img_bytes = f.read()

agent = FlorenceAgent()
res = agent.detect_elements(img_bytes)

for i in range(min(5, len(res))):
    print(res[i])

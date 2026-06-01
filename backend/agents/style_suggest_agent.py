import json
from typing import Dict, Any, List
from .qwen_agent import QwenAgent

class StyleSuggestAgent:
    def __init__(self, api_key=None):
        self.qwen_agent = QwenAgent(api_key=api_key)

    def suggest(self, image_bytes: bytes, box_2d: List[int], suggest_type: str) -> Dict[str, Any]:
        """
        Suggests typography or colors based on the image context and bounding box.
        suggest_type: 'typo' or 'color'
        """
        if suggest_type == "typo":
            system_prompt = (
                "You are an expert typography designer. "
                "Analyze the provided image, specifically focusing on the area defined by the bounding box. "
                "Return a strict JSON response containing a list of 3 suggested Google Fonts that would improve the design. "
                "Schema:\n"
                "{\n"
                '  "fonts": [\n'
                '    {\n'
                '      "name": "Font Name (e.g., Inter)",\n'
                '      "url": "https://fonts.googleapis.com/css2?family=Font+Name",\n'
                '      "css_fallback": "sans-serif",\n'
                '      "reason": "Short reason in English"\n'
                '    }\n'
                '  ]\n'
                "}\n"
            )
            instruction = f"Provide typography suggestions for the text in the bounding box region: {box_2d}. Return JSON."
        elif suggest_type == "color":
            system_prompt = (
                "You are an expert color theorist. "
                "Analyze the provided image and suggest a color palette (in HEX codes) that would improve the harmony and contrast, especially around the bounding box area. "
                "Return a strict JSON response. "
                "Schema:\n"
                "{\n"
                '  "palette": [\n'
                '    {"hex": "#FFFFFF", "role": "Primary text", "reason": "Short reason in English"},\n'
                '    {"hex": "#000000", "role": "Background", "reason": "Short reason in English"}\n'
                '  ]\n'
                "}\n"
                "Provide 4-5 colors in the palette."
            )
            instruction = f"Provide a color palette suggestion for the region: {box_2d}. Return JSON."
        else:
            raise ValueError(f"Invalid suggest_type: {suggest_type}")

        # Use QwenAgent to analyze the image with the specific prompt
        try:
            result = self.qwen_agent.analyze(
                image_bytes=image_bytes,
                system_prompt=system_prompt,
                instruction=instruction,
                mime_type="image/jpeg"
            )
            return result
        except Exception as e:
            print(f"[StyleSuggestAgent] Error: {e}")
            # Fallback mock data in case of parsing error
            if suggest_type == "typo":
                return {
                    "fonts": [
                        {"name": "Inter", "url": "https://fonts.googleapis.com/css2?family=Inter", "css_fallback": "sans-serif", "reason": "Fallback font - AI connection error"},
                        {"name": "Playfair Display", "url": "https://fonts.googleapis.com/css2?family=Playfair+Display", "css_fallback": "serif", "reason": "Elegant and modern"}
                    ]
                }
            else:
                return {
                    "palette": [
                        {"hex": "#FFFFFF", "role": "Text Light", "reason": "Fallback color"},
                        {"hex": "#1A1A1A", "role": "Background Dark", "reason": "Excellent contrast"}
                    ]
                }

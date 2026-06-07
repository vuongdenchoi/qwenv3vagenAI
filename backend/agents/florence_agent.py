from __future__ import annotations
import torch
from transformers import AutoProcessor, AutoModelForCausalLM
from PIL import Image
import io

class FlorenceAgent:
    def __init__(self, model_id="microsoft/Florence-2-base", device="cpu"):
        self.device = device
        self.model_id = model_id
        self.processor = None
        self.model = None

    def _ensure_loaded(self):
        if self.model is None:
            print(f"[FlorenceAgent] Loading model {self.model_id} on {self.device}...")
            # Note: trust_remote_code=True is required for Florence-2
            self.processor = AutoProcessor.from_pretrained(self.model_id, trust_remote_code=True)
            self.model = AutoModelForCausalLM.from_pretrained(self.model_id, trust_remote_code=True).to(self.device)
            self.model.eval()
            print("[FlorenceAgent] Model loaded successfully.")

    def detect_elements(self, image_bytes: bytes) -> list[dict]:
        """
        Runs object detection / OCR on the image.
        Returns a list of dicts: {"box_2d": [x1, y1, x2, y2], "label": str, "score": float}
        Coordinates are normalized to grid 0-1000.
        """
        try:
            self._ensure_loaded()
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            
            # We run '<OD>' task
            task_prompt = '<OD>'
            inputs = self.processor(text=task_prompt, images=image, return_tensors="pt").to(self.device)
            
            with torch.no_grad():
                generated_ids = self.model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=1024,
                    num_beams=3
                )
            
            generated_text = self.processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
            parsed_answer = self.processor.post_process_generation(
                generated_text, 
                task=task_prompt, 
                image_size=(image.width, image.height)
            )
            
            od_results = parsed_answer.get('<OD>', {})
            bboxes = od_results.get('bboxes', [])
            labels = od_results.get('labels', [])
            
            detected = []
            img_w, img_h = image.size
            for box, label in zip(bboxes, labels):
                # Florence-2 box is in absolute pixel coordinates [x1, y1, x2, y2]
                # We normalize it to Qwen-VL grid 0-1000
                x1 = int(box[0] / img_w * 1000)
                y1 = int(box[1] / img_h * 1000)
                x2 = int(box[2] / img_w * 1000)
                y2 = int(box[3] / img_h * 1000)
                
                # Clamp coordinates to 0-1000
                x1 = max(0, min(x1, 1000))
                y1 = max(0, min(y1, 1000))
                x2 = max(0, min(x2, 1000))
                y2 = max(0, min(y2, 1000))
                
                # Filter out collapsed boxes
                if (x2 - x1) >= 5 and (y2 - y1) >= 5:
                    detected.append({
                        "box_2d": [x1, y1, x2, y2],
                        "label": label,
                        "score": 0.85
                    })
            
            # Run '<OCR_WITH_REGION>' to capture text areas
            print("[FlorenceAgent] Running OCR_WITH_REGION to capture UI text components...")
            task_prompt = '<OCR_WITH_REGION>'
            inputs = self.processor(text=task_prompt, images=image, return_tensors="pt").to(self.device)
            with torch.no_grad():
                generated_ids = self.model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=1024,
                    num_beams=3
                )
            generated_text = self.processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
            parsed_answer = self.processor.post_process_generation(
                generated_text, 
                task=task_prompt, 
                image_size=(image.width, image.height)
            )
            ocr_results = parsed_answer.get('<OCR_WITH_REGION>', {})
            quad_boxes = ocr_results.get('quad_boxes', [])
            ocr_labels = ocr_results.get('labels', [])
            for qbox, olabel in zip(quad_boxes, ocr_labels):
                xs = qbox[0::2]
                ys = qbox[1::2]
                bx1, bx2 = min(xs), max(xs)
                by1, by2 = min(ys), max(ys)
                
                x1 = int(bx1 / img_w * 1000)
                y1 = int(by1 / img_h * 1000)
                x2 = int(bx2 / img_w * 1000)
                y2 = int(by2 / img_h * 1000)
                
                x1 = max(0, min(x1, 1000))
                y1 = max(0, min(y1, 1000))
                x2 = max(0, min(x2, 1000))
                y2 = max(0, min(y2, 1000))
                
                if (x2 - x1) >= 5 and (y2 - y1) >= 5:
                    detected.append({
                        "box_2d": [x1, y1, x2, y2],
                        "label": f"text: {olabel}",
                        "score": 0.80
                    })
            
            return detected
        except Exception as e:
            print(f"[FlorenceAgent] Error running local Florence-2: {e}")
            return []

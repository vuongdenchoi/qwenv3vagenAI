from __future__ import annotations
import torch
from transformers import OwlViTProcessor, OwlViTForObjectDetection
from PIL import Image
import io

class OwlViTAgent:
    def __init__(self, model_id="google/owlvit-base-patch32", device="cpu"):
        self.device = device
        self.model_id = model_id
        self.processor = None
        self.model = None

    def _ensure_loaded(self):
        if self.model is None:
            print(f"[OwlViTAgent] Loading model {self.model_id} on {self.device}...")
            self.processor = OwlViTProcessor.from_pretrained(self.model_id)
            self.model = OwlViTForObjectDetection.from_pretrained(self.model_id).to(self.device)
            self.model.eval()
            print("[OwlViTAgent] Model loaded successfully.")

    def detect_elements(self, image_bytes: bytes, labels: list[str] = None) -> list[dict]:
        """
        Runs open-vocabulary object detection.
        Labels list example: ["button", "input field", "text label", "icon", "logo", "header", "card"]
        """
        try:
            self._ensure_loaded()
            if not labels:
                labels = ["button", "input field", "text label", "icon", "logo", "header", "card"]
                
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            
            # Format text queries
            inputs = self.processor(text=[labels], images=image, return_tensors="pt").to(self.device)
            
            with torch.no_grad():
                outputs = self.model(**inputs)
                
            # Post-process results
            target_sizes = torch.tensor([image.size[::-1]]).to(self.device)
            results = self.processor.post_process_object_detection(outputs, threshold=0.1, target_sizes=target_sizes)
            
            # Results is a list of dicts, one for each image
            predictions = results[0]
            boxes = predictions["boxes"].cpu().numpy()
            scores = predictions["scores"].cpu().numpy()
            label_indices = predictions["labels"].cpu().numpy()
            
            detected = []
            img_w, img_h = image.size
            for box, score, label_idx in zip(boxes, scores, label_indices):
                # Box format is [xmin, ymin, xmax, ymax] in pixels
                x1 = int(box[0] / img_w * 1000)
                y1 = int(box[1] / img_h * 1000)
                x2 = int(box[2] / img_w * 1000)
                y2 = int(box[3] / img_h * 1000)
                
                # Clamp coordinates to 0-1000
                x1 = max(0, min(x1, 1000))
                y1 = max(0, min(y1, 1000))
                x2 = max(0, min(x2, 1000))
                y2 = max(0, min(y2, 1000))
                
                if (x2 - x1) >= 5 and (y2 - y1) >= 5:
                    detected.append({
                        "box_2d": [x1, y1, x2, y2],
                        "label": labels[label_idx],
                        "score": float(score)
                    })
                    
            return detected
        except Exception as e:
            print(f"[OwlViTAgent] Error running local OWL-ViT: {e}")
            return []

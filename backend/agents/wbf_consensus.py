from __future__ import annotations

def calculate_iou(boxA: list[int], boxB: list[int]) -> float:
    """Calculates Intersection over Union (IoU) of two bounding boxes [x1, y1, x2, y2]."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    
    interArea = max(0, xB - xA) * max(0, yB - yA)
    
    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    
    unionArea = float(boxAArea + boxBArea - interArea)
    if unionArea == 0:
        return 0.0
    return interArea / unionArea

def fuse_boxes(boxA: list[int], scoreA: float, boxB: list[int], scoreB: float) -> list[int]:
    """Fuses two boxes using weight based on their scores."""
    total_score = scoreA + scoreB
    if total_score == 0:
        return boxA
    x1 = int((boxA[0] * scoreA + boxB[0] * scoreB) / total_score)
    y1 = int((boxA[1] * scoreA + boxB[1] * scoreB) / total_score)
    x2 = int((boxA[2] * scoreA + boxB[2] * scoreB) / total_score)
    y2 = int((boxA[3] * scoreA + boxB[3] * scoreB) / total_score)
    return [x1, y1, x2, y2]

def merge_boxes(florence_boxes: list[dict], owlvit_boxes: list[dict], iou_threshold: float = 0.5) -> list[dict]:
    """
    Fuses and filters boxes detected by Agent 1A (Florence-2) and Agent 1B (OWL-ViT).
    - If boxes overlap with IoU >= iou_threshold, they are merged.
    - Non-overlapping boxes are kept only if their confidence score is high (> 0.8).
    """
    fused_boxes = []
    used_owl = set()

    for f_item in florence_boxes:
        f_box = f_item["box_2d"]
        f_score = f_item.get("score", 0.8)
        f_label = f_item.get("label", "")

        best_iou = 0.0
        best_owl_idx = -1

        for idx, o_item in enumerate(owlvit_boxes):
            if idx in used_owl:
                continue
            iou = calculate_iou(f_box, o_item["box_2d"])
            if iou > best_iou:
                best_iou = iou
                best_owl_idx = idx

        if best_iou >= iou_threshold and best_owl_idx != -1:
            # Consensus found! Merge them
            o_item = owlvit_boxes[best_owl_idx]
            used_owl.add(best_owl_idx)
            
            # Do not average boxes. Florence-2 is much more accurate than OWL-ViT.
            fused_box = f_box
            # Choose the label that is more detailed (e.g. contains "text:" or is not a generic label)
            o_label = o_item["label"]
            if f_label.startswith("text:") and not o_label.startswith("text:"):
                merged_label = f_label
            elif len(f_label) > len(o_label):
                merged_label = f_label
            else:
                merged_label = o_label

            fused_boxes.append({
                "box_2d": fused_box,
                "label": merged_label,
                "score": (f_score + o_item["score"]) / 2,
                "consensus": True
            })
        else:
            # No matching OWL-ViT box. Keep if Florence-2 has high confidence
            if f_score >= 0.8:
                fused_boxes.append({
                    "box_2d": f_box,
                    "label": f_label,
                    "score": f_score,
                    "consensus": False
                })

    # Add remaining OWL-ViT boxes if they have high confidence
    for idx, o_item in enumerate(owlvit_boxes):
        if idx not in used_owl:
            if o_item["score"] >= 0.8:
                fused_boxes.append({
                    "box_2d": o_item["box_2d"],
                    "label": o_item["label"],
                    "score": o_item["score"],
                    "consensus": False
                })

    return fused_boxes

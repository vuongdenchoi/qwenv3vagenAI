from __future__ import annotations

class ErrorAggregator:
    def __init__(self):
        pass

    def aggregate(self, geom_errors: list[dict], sem_errors: list[dict]) -> list[dict]:
        """
        Merges geometric and semantic errors. Deduplicates errors pointing to the same box.
        Each error in the output list will have:
        - "c": [x1, y1, x2, y2] (0-1000 grid coordinates)
        - "r": "Vấn đề: ... Khuyến nghị: ..." (reason combined format)
        - "s": "critical" | "major" | "minor" (severity)
        - "g": "color_theory" | "typography" | "layout_rules" | ... (category)
        """
        all_errors = geom_errors + sem_errors
        merged = []
        
        # Group errors by bounding box coordinates
        for err in all_errors:
            box = err["box_2d"]
            issue = err["issue"]
            suggestion = err["suggestion"]
            severity = err["severity"]
            category = err["category"]
            
            reason = f"Vấn đề: {issue} Khuyến nghị: {suggestion}"
            
            found = False
            for m_err in merged:
                # If the box is exactly the same, append the reason
                if m_err["c"] == box:
                    # Append reason if it is a new issue
                    if issue[:30] not in m_err["r"]:
                        m_err["r"] += f" | {reason}"
                        # Elevate severity if the new error is more severe
                        sev_weight = {"critical": 3, "major": 2, "minor": 1}
                        if sev_weight.get(severity, 0) > sev_weight.get(m_err["s"], 0):
                            m_err["s"] = severity
                    found = True
                    break
            
            if not found:
                merged.append({
                    "c": box,
                    "r": reason,
                    "s": severity,
                    "g": category
                })
                
        # Sort by severity weight (Critical -> Major -> Minor)
        sev_weight = {"critical": 3, "major": 2, "minor": 1}
        merged.sort(key=lambda x: sev_weight.get(x["s"], 0), reverse=True)
        return merged

from collections import defaultdict, Counter

SEVERITY_ORDER = {"severe": 0, "moderate": 1, "minor": 2, "ok": 3}

def aggregate(dna: dict, asset_results: list) -> dict:
    # Overview counts
    severity_counts = Counter(a.get("severity", "ok") for a in asset_results)
    avg_score = sum(a.get("brand_score", 100) for a in asset_results) / max(len(asset_results), 1)
    
    # Group issues by category
    issue_groups = defaultdict(list)
    for asset in asset_results:
        for issue in asset.get("issues", []):
            issue_groups[issue.get("category", "other")].append({
                "asset_id": asset.get("asset_id", "unknown"),
                "brand_score": asset.get("brand_score", 100),
                "description": issue.get("description", ""),
                "severity": issue.get("severity", "minor"),
                "suggestion": issue.get("suggestion", "")
            })
    
    # Sort asset details by severity (worst first)
    sorted_assets = sorted(asset_results, key=lambda x: SEVERITY_ORDER.get(x.get("severity", "ok"), 3))
    
    return {
        "overview": {
            "total_assets": len(asset_results),
            "avg_brand_score": round(avg_score, 1),
            "ok_count": severity_counts.get("ok", 0),
            "minor_count": severity_counts.get("minor", 0),
            "moderate_count": severity_counts.get("moderate", 0),
            "severe_count": severity_counts.get("severe", 0),
        },
        "visual_dna": dna,
        "issue_groups": {
            cat: sorted(issues, key=lambda x: SEVERITY_ORDER.get(x["severity"], 3))
            for cat, issues in issue_groups.items()
        },
        "asset_details": sorted_assets
    }

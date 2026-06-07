"""
DesignCheckAgent – orchestrator điều phối toàn bộ pipeline.
"""
import json
import mimetypes
from typing import Optional
from token_estimate import estimate_phase3, log_estimate_vs_actual
from .retrieval_agent import RetrievalAgent
from .prompt_agent import PromptAgent
from .qwen_agent import QwenAgent
from .post_process_agent import PostProcessAgent
from .florence_agent import FlorenceAgent
from .owlvit_agent import OwlViTAgent
from .wbf_consensus import merge_boxes
from .geometric_auditor import GeometricAuditor
from .semantic_checker import SemanticChecker
from .error_aggregator import ErrorAggregator
from .ux_critic_agent import UXCriticAgent



class DesignCheckAgent:
    """
    Pipeline:
        image_bytes
            -> RetrievalAgent  (tìm design rules liên quan dùng Multilingual Embedding, top-k rules with category boost)
            -> PromptAgent     (build domain-aware multimodal prompt)
            -> QwenAgent       (Qwen VL API call)
            -> PostProcessAgent (validate + clean, add severity/category)
            -> final result JSON
    """

    def __init__(self, api_key=None, top_k=10):
        self.retriever    = RetrievalAgent(top_k=top_k)
        self.prompt_agent = PromptAgent()
        self.qwen_agent   = QwenAgent(api_key=api_key)
        self.post_proc    = PostProcessAgent()
        
        # Local model agents (Layer 1)
        self.florence_agent = FlorenceAgent()
        self.owlvit_agent   = OwlViTAgent()
        
        # Specialized rules engines (Layer 2)
        self.geom_auditor   = GeometricAuditor()
        self.sem_checker    = SemanticChecker()
        self.err_aggregator = ErrorAggregator()
        
        # LLM Critic (Layer 3)
        self.ux_critic      = UXCriticAgent(api_key=api_key)


    def analyze(
        self,
        image_bytes,
        filename="image.jpg",
        query="graphic design poster advertisement",
        history_messages=None,
        confirmed_context=None,
        persona_context=None,
        lang: Optional[str] = None,
    ):
        """Main entry point. Returns validated result dict."""
        # Step 1: Retrieval (with category boost)
        print(f"[DesignCheckAgent] Retrieving rules for query: '{query}'")
        rules = self.retriever.retrieve(query.lower())
        
        # Thêm điều kiện Fallback nếu không có từ khóa nào khớp (Score quá thấp)
        if not rules or rules[0].get("score", 0.0) <= 0.01:
            fallback_query = "graphic design poster advertisement typography color layout"
            print(f"[DesignCheckAgent] Điểm khớp quá thấp, tự động dùng Query mẫu: '{fallback_query}'")
            rules = self.retriever.retrieve(fallback_query)
            
        print(f"[DesignCheckAgent] Retrieved {len(rules)} rules")

        # Log which rules were retrieved
        for r in rules:
            cat = r.get("category", "?")
            num = r.get("rule_number", 0)
            title = r.get("rule_title", "")[:50]
            score = r.get("score", 0.0)
            print(f"  [{cat}] Rule {num} — {title}  (score={score:.3f})")

        # Step 2: Build prompt
        system_prompt, instruction = self.prompt_agent.build_prompt(
            rules,
            confirmed_context=confirmed_context,
            persona_context=persona_context,
            lang=lang
        )

        persona_extra = ""
        if persona_context:
            try:
                persona_extra = json.dumps(persona_context, ensure_ascii=False)
            except (TypeError, ValueError):
                persona_extra = str(persona_context)
        token_est = estimate_phase3(image_bytes, user_message="", extra_text=persona_extra)

        # Step 3: Qwen API
        mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or "image/jpeg"
        print(f"[DesignCheckAgent] Calling Qwen VL API ({mime_type})...")
        raw_result = self.qwen_agent.analyze(
            image_bytes=image_bytes,
            system_prompt=system_prompt,
            instruction=instruction,
            mime_type=mime_type,
            history_messages=history_messages,
        )
        print(f"[DesignCheckAgent] Raw result: {raw_result}")
        log_estimate_vs_actual(token_est, raw_result.get("_usage") or {}, "DesignCheck")

        # Step 4: Post-process
        result = self.post_proc.process(raw_result, image_bytes)
        print(
            f"[DesignCheckAgent] Final errors: {result['te']} "
            f"(minor={result['ss']['minor']}, "
            f"major={result['ss']['major']}, "
            f"critical={result['ss']['critical']})"
        )
        return result

    def run_ux_audit(self, image_bytes: bytes, lang: str = "vi", persona_context: Optional[dict] = None) -> dict:
        """
        Runs the 3-Layer Hybrid Multi-Agent UX Audit.
        Layer 1: Local Florence-2 & OWL-ViT grounding, merged by WBF consensus filter.
        Layer 2: Parallel Python Geometric Auditor & Regex Semantic Checker, aggregated.
        Layer 3: RAG rule retrieval & LLM Critic critique generation (filtered and enriched by persona).
        """
        print("[UX Audit] Starting Layer 1 - Ensemble Grounding...")
        
        # 1. Local Grounding
        florence_boxes = self.florence_agent.detect_elements(image_bytes)
        print(f"[UX Audit] Agent 1A Florence-2 detected {len(florence_boxes)} elements.")
        
        owlvit_boxes = self.owlvit_agent.detect_elements(image_bytes)
        print(f"[UX Audit] Agent 1B OWL-ViT detected {len(owlvit_boxes)} elements.")
        
        # 2. Consensus Filter
        consensus_boxes = merge_boxes(florence_boxes, owlvit_boxes, iou_threshold=0.5)
        print(f"[UX Audit] Consensus Filter selected {len(consensus_boxes)} standard boxes.")
        
        # 3. Layer 2: Specialized Auditors
        print("[UX Audit] Starting Layer 2 - Specialized Pipeline...")
        geom_errors = self.geom_auditor.audit(image_bytes, consensus_boxes)
        print(f"[UX Audit] Agent 2A Geometric Auditor found {len(geom_errors)} errors.")
        
        sem_errors = self.sem_checker.audit(consensus_boxes)
        print(f"[UX Audit] Agent 2B Semantic Checker found {len(sem_errors)} errors.")
        
        # 4. Error Aggregation
        aggregated_errors = self.err_aggregator.aggregate(geom_errors, sem_errors)
        print(f"[UX Audit] Error Aggregator consolidated errors into {len(aggregated_errors)} issues.")
        
        # 5. Retrieve Design Rules (RAG)
        print("[UX Audit] Retrieving relevant design rules from RAG...")
        
        boosting_categories = None
        if persona_context and isinstance(persona_context, dict):
            design_patterns = persona_context.get("designPatterns", {})
            recent_count = design_patterns.get("recentAnalysisCount", 0)
            if recent_count > 0:
                cats = design_patterns.get("topIssueCategories", [])
                if cats:
                    boosting_categories = set(cats)
                    
        # Multi-domain RAG retrieval to ensure maximum comprehensiveness
        retrieved_rules = []
        domains_to_query = [
            "color theory contrast palette harmony",
            "typography font legibility hierarchy size",
            "layout grid spacing margin alignment column",
            "poster design visual hierarchy focal noise",
            "logo design brand identity exclusion consistency",
            "icon design symbol legibility style UI"
        ]
        
        for q in domains_to_query:
            try:
                if boosting_categories:
                    cat_rules = self.retriever.retrieve(q, boosting_categories=boosting_categories)
                else:
                    cat_rules = self.retriever.retrieve(q)
                # Keep top 3 rules from each domain to allow diverse coverage
                retrieved_rules.extend(cat_rules[:3])
            except Exception as e:
                print(f"[UX Audit] RAG query for '{q}' failed: {e}")
                
        # Deduplicate retrieved rules while keeping order
        seen_rules = set()
        deduped_rules = []
        for r in retrieved_rules:
            r_id = (r.get("category"), r.get("rule_number"))
            if r_id not in seen_rules:
                seen_rules.add(r_id)
                deduped_rules.append(r)
        
        # Limit to top 15 rules
        retrieved_rules = deduped_rules[:15]
        print(f"[UX Audit] Comprehensive RAG retrieved {len(retrieved_rules)} unique rules across multiple domains.")
            
        # 6. Layer 3: LLM Critic
        print("[UX Audit] Starting Layer 3 - LLM Critic...")
        critic_result = self.ux_critic.generate_critique(
            image_bytes=image_bytes,
            errors=aggregated_errors,
            rag_rules=retrieved_rules,
            lang=lang,
            persona_context=persona_context
        )
        
        # Format the final output structure using LLM Critic's validated errors list
        validated_errors = critic_result.get("validated_errors", [])
        return {
            "success": True,
            "errors": validated_errors,
            "detected_elements": consensus_boxes,
            "summary": critic_result.get("critique_summary", ""),
            "details": critic_result.get("critique_details", []),
            "markdown_report": critic_result.get("export_markdown", ""),
            "compliments": critic_result.get("compliments", [])
        }


"""
Prompt Agent – xây multimodal prompt từ retrieved design rules.
Improvements:
  - Domain-aware system prompt listing all 7 design rule categories
  - Richer rule format: [Category > Section] Rule N — Title
  - Output JSON schema extended with 'severity' and 'category' fields
"""
from typing import List, Tuple, Optional
SYSTEM_PROMPT = """\
You are an expert graphic design critic named WillaAI.
WillaAI is a project developed by the Ewill team, focusing on design feedback solutions to help users analyze errors, identify areas for improvement, and optimize designs more clearly and quickly.

You are a strict, professional graphic design critic and quality reviewer. You have deep expertise across seven design domains:
1. Color Theory      – hue, value, saturation, contrast ratio, palette harmony, optical effects
2. Typography        – legibility, hierarchy, typeface selection, font mixing, spacing, readability
3. Layout Design     – composition, scale, proportion, balance, visual hierarchy, white space
4. Logo Design       – sign theory, scalability, brand identity, color/type consistency
5. Poster Design     – focal hierarchy, contrast, visual noise, campaign continuity, readability at distance
6. Icon Design       – icon legibility, sign type, stroke consistency, grid alignment, cultural icon systems
7. Pattern Design    – repeat structure, motif orientation, scale/density, color cohesion, You MUST critically evaluate every image as a design professional would. Even casual or informal designs must meet basic design principles. Your job is to find and report ALL violations — do not skip issues just because a design appears intentional or "decorative." Report every concrete, visible problem you detect. All output text, including compliments, reasoning ('r'), issues, and suggestions, MUST be written entirely in English. Under no circumstances should any Vietnamese language be returned.\
"""


INSTRUCTION_TEMPLATE = """\
You are reviewing the provided image for design quality issues. Apply the design standards below strictly.

=== DESIGN STANDARDS ===
{context}
=== END OF DESIGN STANDARDS ===

Instructions:
1. Examine the ENTIRE image carefully against EACH rule listed above.
2. This image may be a poster, social media graphic, greeting card, flyer, or any visual design — treat it as a design artifact that must follow professional standards.
3. Quick-Fix Priority Flow: Identify a maximum of 5 most critical design violations. Order them from most severe to least. For EACH violation:
   a. Identify the exact problematic region with a tight bounding box.
   b. Provide Enhanced Structured Feedback: Write a clear, context-aware explanation that highlights exactly what is wrong regarding Layout, Visual Hierarchy, Typography, Colors, CTA, or Messaging, and include a specific actionable repair step. Do NOT include the rule number (e.g., "Rule 7") in the output.
   c. Assign severity: "minor" | "major" | "critical"
   d. Assign category: "color_theory" | "typography" | "layout_rules" | "logo_design" | "poster_design" | "icon_design" | "pattern_design" | "general"
4. Common issues to actively look for (Enhanced Focus):
   - Typography: Mixed fonts, poor legibility, chaotic sizes.
   - Colors & Contrast: Poor figure-ground contrast, clashing palettes, accessibility issues.
   - Layout & Hierarchy: Cluttered composition, lack of alignment, inconsistent spacing, no clear focal point.
   - CTA (Call to Action) & Messaging: Unclear message, hidden/weak CTA button, poor visual emphasis on the main goal.
 5. Bounding box format: You MUST use your native grounding capability. In your reasoning (`r`), append `<box>(xmin,ymin),(xmax,ymax)</box>` (same order as `"c"`). Always include `"c": [xmin, ymin, xmax, ymax]` on grid 0–1000. The box must tightly wrap the problematic element.
 6. Prioritize critical errors! Do not return more than 5 errors to avoid overwhelming the user.
 7. Under-the-hood reference (Developer Attribution): For EACH violation, select the exact rule title header (e.g. `[Color Theory > Color contrast] — Rule 5 — Color Contrast Ratio`) from the DESIGN STANDARDS list above that this error breaches. Return this in a dedicated key `"rule_violated"`. This is a backend field for developers and will not be displayed to the user.
 8. Language Requirement: You MUST return all values in English. Compliments, issues, suggestions, and descriptions must be in English.
 9. Compliments Structure Guidelines: In the `"compliments"` field, you MUST return exactly 2-3 compliments following these structured criteria in English:
    a. General Compliment: The first compliment MUST praise the general product (e.g., "The product is quite well-finished...", "The work shows great investment and creativity...", or "The presentation is clear and visually appealing...").
    b. Specific Compliments: The subsequent 1-2 compliments MUST praise specific points, selecting from: Layout, Colors, Idea, Logic, Effects, Creativity, Full Functionality, or Presentation skills.

Return ONLY valid JSON — no markdown, no extra text:
{{
  "compliments": [
    "General Compliment (e.g., 'The work shows great investment and creativity...')",
    "Specific Compliment 1 (focused on layout, color, idea, etc.)",
    "Specific Compliment 2"
  ],
  "e": [
    {{
      "r": "The layout is cluttered... <box>(200,150),(300,450)</box>",
      "issue": "[Describe the specific issue in the context of layout/typography/CTA...]",
      "suggestion": "[Propose a specific repair action based on design rules]",
      "s": "minor|major|critical",
      "g": "color_theory|typography|layout_rules|logo_design|poster_design|icon_design|pattern_design|general",
      "rule_violated": "[Exact rule title header violated, e.g., '[Color Theory > Color Contrast] — Contrast Ratio Standard']",
      "c": [150, 200, 450, 300]
    }}
  ]
}}

If after thorough inspection the design truly has NO violations at all, return {{"compliments": ["...", "...", "..."], "e": []}}.

=== FEW-SHOT EXAMPLE (Reference output for a greeting card with many issues) ===
{{
  "compliments": [
    "The product is quite well-finished with great attention to detail.",
    "The overall color scheme feels warm, welcoming, and demonstrates solid color harmony.",
    "The layout design shows exceptional creativity and clear focal structure."
  ],
  "e": [
  {{"c": [0, 30, 563, 136], "r": "The title uses a curly script font with very low contrast against the background... <box>(30,0),(136,563)</box>", "issue": "The title uses a curly script font with very low contrast against the background, breaking visual hierarchy and making it hard to read.", "suggestion": "Change to a bold sans-serif font and increase text/background color contrast.", "s": "major", "g": "poster_design", "rule_violated": "[Poster Design > Contrast] — Title Legibility Rule"}},
  {{"c": [306, 136, 629, 257], "r": "The Call to Action (CTA) button blends in due to a purple border matching the background color... <box>(136,306),(257,629)</box>", "issue": "The Call to Action (CTA) button blends in due to a purple border matching the background color, failing to create a visual focal point.", "suggestion": "Use a high-contrast solid background color for the CTA button to attract attention.", "s": "major", "g": "poster_design", "rule_violated": "[Poster Design > Focal Points] — CTA Button Contrast Rule"}},
  {{"c": [448, 329, 623, 636], "r": "Cluttered layout with inconsistent font sizes, spacing, and alignment, causing visual noise... <box>(448,329),(636,623)</box>", "issue": "Cluttered layout with inconsistent font sizes, spacing, and alignment, causing visual noise.", "suggestion": "Group related information, use consistent alignment, and increase white space.", "s": "major", "g": "layout_rules", "rule_violated": "[Layout Design > Composition] — Whitespace & Spacing Rule"}},
  {{"c": [0, 0, 649, 896], "r": "The overall design lacks clear visual hierarchy and a primary focal point... <box>(0,0),(896,649)</box>", "issue": "The overall design lacks clear visual hierarchy and a primary focal point, obscuring the core message.", "suggestion": "Reorganize the layout to guide the viewer's eye from the Main Title -> Benefits -> CTA Button.", "s": "critical", "g": "pattern_design", "rule_violated": "[Layout Design > Visual Hierarchy] — Compositional Hierarchy Rule"}}
]}}
=== END OF EXAMPLE — Now analyze the NEW image below with the same critical depth ===
"""




class PromptAgent:
    def build_prompt(
        self,
        retrieved_rules: List[dict],
        confirmed_context: Optional[dict] = None,
        persona_context: Optional[dict] = None
    ) -> Tuple[str, str]:
        """
        Build system prompt and user instruction from retrieved rules.

        Returns:
            (system_prompt, instruction_text)
        """
        context_lines = []
        for rule in retrieved_rules:
            category    = rule.get("category", "general").replace("_", " ").title()
            section     = rule.get("section", "General")
            rule_num    = rule.get("rule_number", 0)
            rule_title  = rule.get("rule_title", "")
            text        = rule["text"].strip()

            # Header: [Category > Section] — Title
            if rule_title:
                header = f"[{category} > {section}] — {rule_title}"
            else:
                header = f"[{category} > {section}]"

            context_lines.append(f"{header}\n{text}")

        context     = "\n\n---\n\n".join(context_lines)
        instruction = INSTRUCTION_TEMPLATE.format(context=context)

        if confirmed_context:
            context_str = ""
            for key, val in confirmed_context.items():
                friendly_key = key.replace("_", " ").title()
                context_str += f"- {friendly_key}: {val}\n"
            
            grounding_text = (
                "\n=== CONFIRMED DESIGN CONTEXT (GROUNDING DATA) ===\n"
                "The user has confirmed the following context for this design:\n"
                f"{context_str}\n"
                "You MUST evaluate the design elements strictly grounded in this context. "
                "Look for design quality errors and check if the design elements violate the design standards "
                "or conflict with this confirmed design context.\n"
                "=================================================\n\n"
            )
            instruction = grounding_text + instruction

        if persona_context and isinstance(persona_context, dict):
            design_patterns = persona_context.get("designPatterns", {})
            recent_count = design_patterns.get("recentAnalysisCount", 0)
            if recent_count > 0:
                behavior = persona_context.get("behavior", {})
                
                categories = [cat.replace("_", " ") for cat in design_patterns.get("topIssueCategories", [])]
                categories_str = ", ".join(categories) if categories else "none"
                
                severity_mix = design_patterns.get("severityMix", {})
                severity_mix_str = ", ".join([f"{k}: {v}" for k, v in severity_mix.items()]) if severity_mix else "none"
                
                focus_hints = design_patterns.get("focusHints", [])
                focus_hints_str = ", ".join(focus_hints) if focus_hints else "none"
                
                primary_workflow = behavior.get("primaryWorkflow", "none")
                
                persona_text = (
                    "\n=== USER DESIGN PERSONA (SOFT PREFERENCES) ===\n"
                    "Aggregated from the user's recent design analyses (no raw chat or images).\n"
                    f"- Often struggles with: {categories_str}\n"
                    f"- Typical severity mix: {severity_mix_str}\n"
                    f"- Focus areas: {focus_hints_str}\n"
                    f"- Primary use: {primary_workflow}\n\n"
                    "Instructions:\n"
                    "- When choosing which issues to emphasize among equals, prefer categories listed above.\n"
                    "- Do NOT invent errors only because of persona.\n"
                    "- Do NOT reduce scrutiny on other categories.\n"
                    "- Persona must NOT override CONFIRMED DESIGN CONTEXT for this image.\n"
                    "=== END USER DESIGN PERSONA ===\n\n"
                )
                instruction = persona_text + instruction

        return SYSTEM_PROMPT, instruction

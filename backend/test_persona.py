import json
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

import os
os.environ["DASHSCOPE_API_KEY"] = "mock-key"

# Import the app and the prompt/agent classes
import sys
sys.path.append(".")
from main import app, parse_persona
from agents.prompt_agent import PromptAgent
from agents.design_check_agent import DesignCheckAgent

client = TestClient(app)

# 1. Test parsing helper function directly
def test_parsing_helper():
    print("\n--- [Test 1] Testing parse_persona helper ---")
    
    # Test None
    assert parse_persona(None) is None, "Failed for None input"
    
    # Test Empty/Whitespace
    assert parse_persona("") is None, "Failed for empty string"
    assert parse_persona("   ") is None, "Failed for whitespace string"
    
    # Test Invalid JSON
    assert parse_persona("invalid-json") is None, "Failed for invalid JSON"
    
    # Test Non-dict JSON
    assert parse_persona('["not-a-dict"]') is None, "Failed for non-dict JSON"
    
    # Test Incorrect schema version
    assert parse_persona('{"schemaVersion": 2, "profile": {}}') is None, "Failed for schemaVersion != 1"
    
    # Test Correct schema version
    valid_json = '{"schemaVersion": 1, "profile": {"occupationLabel": "Designer"}, "designPatterns": {"recentAnalysisCount": 2}}'
    parsed = parse_persona(valid_json)
    assert parsed is not None, "Failed to parse valid JSON"
    assert parsed.get("schemaVersion") == 1, "Incorrect parsed schemaVersion"
    assert parsed["profile"]["occupationLabel"] == "Designer", "Incorrect parsed profile properties"
    print("✓ All parse_persona helper tests passed!")

# 2. Test PromptAgent Prompt Injection directly
def test_prompt_injection():
    print("\n--- [Test 2] Testing PromptAgent build_prompt injection ---")
    agent = PromptAgent()
    rules = [{"category": "typography", "section": "Fonts", "text": "Always align text properly."}]
    
    # Case A: No persona
    _, instr_a = agent.build_prompt(rules, confirmed_context=None, persona_context=None)
    assert "=== USER DESIGN PERSONA" not in instr_a, "Persona block injected when None"
    
    # Case B: Persona with recentAnalysisCount = 0
    persona_zero = {
        "schemaVersion": 1,
        "designPatterns": {
            "recentAnalysisCount": 0,
            "topIssueCategories": ["typography"]
        }
    }
    _, instr_b = agent.build_prompt(rules, confirmed_context=None, persona_context=persona_zero)
    assert "=== USER DESIGN PERSONA" not in instr_b, "Persona block injected when recentAnalysisCount is 0"
    
    # Case C: Valid persona
    persona_valid = {
        "schemaVersion": 1,
        "profile": {
            "occupationLabel": "Graphic Designer"
        },
        "behavior": {
            "primaryWorkflow": "ANALYZE"
        },
        "designPatterns": {
            "recentAnalysisCount": 3,
            "topIssueCategories": ["typography", "layout_rules"],
            "severityMix": {
                "major": 4,
                "critical": 2
            },
            "focusHints": [
                "major typography",
                "critical layout_rules"
            ]
        }
    }
    
    _, instr_c = agent.build_prompt(rules, confirmed_context=None, persona_context=persona_valid)
    assert "=== USER DESIGN PERSONA (SOFT PREFERENCES) ===" in instr_c, "Persona header not injected"
    assert "- Often struggles with: typography, layout rules" in instr_c, "Failed to clean or format categories"
    assert "- Typical severity mix: major: 4, critical: 2" in instr_c, "Failed to format severity mix"
    assert "- Focus areas: major typography, critical layout_rules" in instr_c, "Failed to format focus hints"
    assert "- Primary use: ANALYZE" in instr_c, "Failed to format primary workflow"
    print("✓ All prompt injection tests passed!")

# 3. Test End-to-End unified_chat pipeline using TestClient and mock QwenVL API
def test_unified_chat_pipeline():
    print("\n--- [Test 3] Testing unified_chat pipeline with TestClient ---")
    
    # We will mock the get_agent() or the DesignCheckAgent inside main to inspect the generated prompts
    import main
    
    original_agent = main.get_agent()
    mock_agent = DesignCheckAgent()
    
    # Mock retriever and post processor
    mock_agent.retriever = MagicMock()
    mock_agent.retriever.retrieve.return_value = [
        {"category": "typography", "section": "Fonts", "rule_number": 1, "rule_title": "Clean Type", "text": "Rule text", "score": 0.9}
    ]
    mock_agent.post_proc = MagicMock()
    mock_agent.post_proc.process.return_value = {
        "te": 1,
        "ss": {"minor": 0, "major": 1, "critical": 0},
        "e": [{"r": "Issue description", "issue": "Some issue", "s": "major"}],
        "compliments": ["Good work"]
    }
    
    # Mock qwen_agent.analyze
    captured_args = {}
    def mock_qwen_analyze(image_bytes, system_prompt, instruction, mime_type, history_messages=None):
        captured_args["system_prompt"] = system_prompt
        captured_args["instruction"] = instruction
        return {
            "compliments": ["Good job"],
            "e": []
        }
    
    mock_agent.qwen_agent = MagicMock()
    mock_agent.qwen_agent.analyze = mock_qwen_analyze
    
    # Inject mock agent into main module
    main.get_agent = lambda: mock_agent
    
    try:
        # A: Call /chat with no persona
        dummy_file = ("test.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")
        response = client.post(
            "/chat",
            data={
                "session_id": "test-session-123",
                "message": "Analyze this design"
            },
            files={"file": dummy_file}
        )
        assert response.status_code == 200
        assert "=== USER DESIGN PERSONA" not in captured_args.get("instruction", ""), "Persona injected when omitted"
        print("  Subtest A (No Persona): ✓ OK")
        
        # B: Call /chat with malformed persona
        captured_args.clear()
        response = client.post(
            "/chat",
            data={
                "session_id": "test-session-123",
                "message": "Analyze this design",
                "persona_context": "bad-json"
            },
            files={"file": dummy_file}
        )
        assert response.status_code == 200
        assert "=== USER DESIGN PERSONA" not in captured_args.get("instruction", ""), "Persona injected with invalid JSON"
        print("  Subtest B (Malformed Persona): ✓ OK")
        
        # C: Call /chat with valid persona
        captured_args.clear()
        persona_valid_str = json.dumps({
            "schemaVersion": 1,
            "profile": {"occupationLabel": "Graphic Designer"},
            "designPatterns": {
                "recentAnalysisCount": 2,
                "topIssueCategories": ["color_theory", "layout_rules"],
                "severityMix": {"major": 2},
                "focusHints": ["major typography"]
            }
        })
        response = client.post(
            "/chat",
            data={
                "session_id": "test-session-123",
                "message": "Analyze this design",
                "persona_context": persona_valid_str
            },
            files={"file": dummy_file}
        )
        assert response.status_code == 200
        instruction = captured_args.get("instruction", "")
        assert "=== USER DESIGN PERSONA (SOFT PREFERENCES) ===" in instruction, "Persona block not injected"
        assert "Often struggles with: color theory, layout rules" in instruction, "Clean categories failure in pipeline"
        print("  Subtest C (Valid Persona): ✓ OK")
        
    finally:
        # Restore original get_agent
        main.get_agent = lambda: original_agent
        
    print("✓ All unified_chat pipeline tests passed!")

if __name__ == "__main__":
    test_parsing_helper()
    test_prompt_injection()
    test_unified_chat_pipeline()
    print("\n=================================")
    print("🎉 ALL VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=================================")

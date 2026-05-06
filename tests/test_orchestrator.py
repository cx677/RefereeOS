from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from backend.agents import orchestrator


PASSED_RECEIPT = {
    "probe": "OpenAI GPT-5.5 reproducibility agent: select and run metric recalculation probe",
    "sandbox_provider": "Daytona",
    "model": "gpt-5.5",
    "status": "passed",
    "commands_run": ["python reproduce_metric.py results.csv"],
    "reported_result": "0.87",
    "observed_result": "0.87",
    "artifact_paths": ["results.csv", "reproduce_metric.py"],
    "stdout_stderr_summary": "macro_f1=0.87",
    "human_followup": "No immediate follow-up needed for this metric.",
    "llm_interpretation": "Artifact rerun reproduced the reported macro F1.",
    "exit_code": 0,
}

FAILED_RECEIPT = {
    **PASSED_RECEIPT,
    "status": "failed",
    "reported_result": "0.91",
    "observed_result": "0.77",
    "stdout_stderr_summary": "macro_f1=0.77",
    "human_followup": "Ask authors to explain the metric mismatch before review.",
    "llm_interpretation": "Artifact rerun did not reproduce the reported macro F1.",
}


class OrchestratorTests(unittest.TestCase):
    def analyze_fixture_with_receipt(self, fixture_id: str, receipt: dict) -> dict:
        with patch.dict(os.environ, {"REFEREEOS_ENABLE_AG2_LLM": "false"}, clear=False):
            with patch.object(orchestrator.DaytonaOpenAIReproRunner, "run", return_value=dict(receipt)):
                return orchestrator.analyze_fixture(fixture_id)

    def test_clean_fixture_remains_ready_for_human_review(self) -> None:
        board = self.analyze_fixture_with_receipt("clean", PASSED_RECEIPT)

        self.assertEqual(board["final_packet"]["triage_recommendation"], "Ready for human review")
        self.assertEqual(board["repro_checks"][0]["status"], "passed")

    def test_suspicious_fixture_remains_possible_integrity_issue(self) -> None:
        board = self.analyze_fixture_with_receipt("suspicious", FAILED_RECEIPT)

        self.assertEqual(board["final_packet"]["triage_recommendation"], "Possible integrity issue")
        self.assertTrue(any(c["category"] == "integrity" and c["severity"] == "high" for c in board["concerns"]))

    def test_repro_concern_links_to_metric_claim(self) -> None:
        board = self.analyze_fixture_with_receipt("suspicious", FAILED_RECEIPT)
        repro_concern = next(c for c in board["concerns"] if c["category"] == "reproducibility")

        linked_claim_ids = [claim["id"] for claim in board["claims"] if repro_concern["id"] in claim["concern_ids"]]

        self.assertEqual(linked_claim_ids, ["claim_002"])

    def test_workflow_high_concern_prevents_ready_recommendation(self) -> None:
        board = {
            "concerns": [{"severity": "high", "category": "workflow"}],
            "repro_checks": [{"status": "passed"}],
        }

        self.assertEqual(orchestrator._triage_recommendation(board), "Needs author clarification before review")

    def test_causal_condition_still_flags_observational_causal_language(self) -> None:
        text = """# Causal Test Paper

## Abstract
This observational benchmark claims causal improvement in outcomes.

## Main Claims
- The method makes causal improvement claims from observational data.

## Methods
The study uses a train/validation/test split and a baseline model.

## Results
The paper reports macro F1 of 0.87.
"""
        with patch.dict(os.environ, {"REFEREEOS_ENABLE_AG2_LLM": "false"}, clear=False):
            with patch.object(orchestrator.DaytonaOpenAIReproRunner, "run", return_value=dict(PASSED_RECEIPT)):
                board = orchestrator.analyze_text(text, source="unit", fixture_meta={"fixture_id": "unit"})

        self.assertTrue(any("Causal language is unsupported" in c["text"] for c in board["concerns"]))

    def test_ag2_fallback_still_produces_packet_without_gemini_key(self) -> None:
        env = {
            "REFEREEOS_ENABLE_AG2_LLM": "true",
            "GEMINI_API_KEY": "",
            "GOOGLE_GEMINI_API_KEY": "",
            "GOOGLE_API_KEY": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch.object(orchestrator.DaytonaOpenAIReproRunner, "run", return_value=dict(PASSED_RECEIPT)):
                board = orchestrator.analyze_fixture("clean")

        self.assertIn(board["metadata"]["ag2_status"], {"missing_key", "unavailable"})
        self.assertTrue(board["final_packet"]["markdown"])


class BetaFeatureTests(unittest.TestCase):
    """Tests for Beta-agent related functions."""

    def test_build_llm_config_prefers_gemini(self) -> None:
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "fake-gemini", "DEEPSEEK_API_KEY": "", "AG2_MODEL": ""},
            clear=False,
        ):
            cfg = orchestrator._build_llm_config(
                orchestrator.AG2Runtime(True, "x", "x", [], True, "gemini-3.1-pro-preview", "ready")
            )
        self.assertEqual(cfg["api_type"], "google")
        self.assertEqual(cfg["api_key"], "fake-gemini")

    def test_build_llm_config_falls_back_to_deepseek(self) -> None:
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "", "GOOGLE_GEMINI_API_KEY": "", "GOOGLE_API_KEY": "",
             "DEEPSEEK_API_KEY": "fake-ds"},
            clear=False,
        ):
            cfg = orchestrator._build_llm_config(
                orchestrator.AG2Runtime(True, "x", "x", [], True, "deepseek-v4-pro", "ready")
            )
        self.assertEqual(cfg["api_type"], "openai")
        self.assertEqual(cfg["api_key"], "fake-ds")
        self.assertIn("base_url", cfg)

    def test_build_llm_config_returns_none_without_keys(self) -> None:
        with patch.dict(
            os.environ,
            {"GEMINI_API_KEY": "", "GOOGLE_GEMINI_API_KEY": "", "GOOGLE_API_KEY": "",
             "DEEPSEEK_API_KEY": ""},
            clear=False,
        ):
            cfg = orchestrator._build_llm_config(
                orchestrator.AG2Runtime(True, "x", "x", [], True, "deepseek-v4-pro", "ready")
            )
        self.assertIsNone(cfg)

    def test_detect_ag2_runtime_ready_with_deepseek_only(self) -> None:
        """P1-5 regression: detect_ag2_runtime should report ready when only DeepSeek key is set."""
        with patch.dict(
            os.environ,
            {"REFEREEOS_ENABLE_AG2_LLM": "true",
             "GEMINI_API_KEY": "", "GOOGLE_GEMINI_API_KEY": "", "GOOGLE_API_KEY": "",
             "DEEPSEEK_API_KEY": "fake-ds"},
            clear=False,
        ):
            rt = orchestrator.detect_ag2_runtime()
        self.assertEqual(rt.status, "ready")
        self.assertTrue(rt.llm_enabled)

    def test_parse_synthesis_with_json(self) -> None:
        import json as _json
        raw = _json.dumps({"summary": "Looks good", "risk_summary": "Low", "human_focus": "Check stats"})
        result = orchestrator._parse_synthesis(raw, "deepseek-v4-pro")
        self.assertEqual(result["summary"], "Looks good")
        self.assertEqual(result["risk_summary"], "Low")

    def test_parse_synthesis_with_plain_text(self) -> None:
        raw = "This paper has some issues with methodology."
        result = orchestrator._parse_synthesis(raw, "gemini-3.1-pro-preview")
        self.assertEqual(result["source"], "AG2 Beta + gemini-3.1-pro-preview")
        self.assertTrue(len(result["summary"]) > 0)


class BetaAsyncTests(unittest.IsolatedAsyncioTestCase):
    """Async tests for Beta-agent synthesis functions."""

    async def test_beta_synthesis_with_mocked_agent(self) -> None:
        """_beta_synthesis() should call area_chair.ask and parse the result."""

        class _FakeReply:
            body = '{"summary": "OK", "risk_summary": "Low", "human_focus": "Check methods"}'

        mock_agent = AsyncMock()
        mock_agent.ask.return_value = _FakeReply()

        with patch("backend.agents.agent_factory.create_agents_for_synthesis", return_value=(mock_agent, mock_agent)):
            with patch("backend.agents.orchestrator._build_llm_config", return_value=None):
                result = await orchestrator._beta_synthesis(
                    "test prompt",
                    {"model": "deepseek-v4-pro", "api_key": "fake",
                     "api_type": "openai", "base_url": "https://api.deepseek.com/v1"},
                )
        self.assertEqual(result["summary"], "OK")
        self.assertEqual(result["risk_summary"], "Low")

    async def test_ag2_area_chair_synthesis_with_mocked_beta(self) -> None:
        """_ag2_area_chair_synthesis() should delegate to _beta_synthesis."""
        with patch.object(orchestrator, "_build_llm_config", return_value={"model": "deepseek-v4-pro", "api_key": "fake"}):
            with patch.object(orchestrator, "_beta_synthesis", new_callable=AsyncMock) as mock_beta:
                mock_beta.return_value = {"source": "test", "summary": "OK", "risk_summary": "", "human_focus": ""}
                rt = orchestrator.AG2Runtime(True, "1.0", "test", [], True, "deepseek-v4-pro", "ready")
                result = orchestrator._ag2_area_chair_synthesis(
                    {"paper": {}, "claims": [], "concerns": [], "repro_checks": []},
                    "Ready for human review",
                    ["CS"],
                    rt,
                )
        self.assertEqual(result["summary"], "OK")


if __name__ == "__main__":
    unittest.main()

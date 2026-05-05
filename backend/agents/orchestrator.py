from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.metadata.related_work import get_related_work
from backend.parsing.injection_scan import scan_for_prompt_injection
from backend.parsing.paper_parser import FIXTURES, load_fixture_text, parse_manuscript_text
from backend.repro.daytona_runner import DaytonaOpenAIReproRunner, DEFAULT_OPENAI_MODEL
from backend.storage.evidence_board import build_empty_board


@dataclass
class AG2Runtime:
    available: bool
    version: str
    label: str
    agents: list[str]
    llm_enabled: bool = False
    llm_model: str | None = None
    status: str = "deterministic"
    error: str | None = None


def detect_ag2_runtime() -> AG2Runtime:
    agents = [
        "intake_agent",
        "methods_statistics_agent",
        "integrity_agent",
        "novelty_literature_agent",
        "reproducibility_agent",
        "area_chair_agent",
    ]

    try:
        import autogen  # type: ignore

        version = getattr(autogen, "__version__", "installed")
    except Exception as exc:
        return AG2Runtime(
            False,
            "not installed",
            "AG2-compatible deterministic workflow (autogen unavailable)",
            agents,
            status="unavailable",
            error=str(exc),
        )

    model = os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")
    enable_llm = os.getenv("REFEREEOS_ENABLE_AG2_LLM", "false").lower() == "true"
    if not enable_llm:
        return AG2Runtime(
            True,
            version,
            f"AG2 {version} installed; deterministic synthesis",
            agents,
            llm_model=model,
            status="disabled",
        )
    if not _gemini_api_key():
        return AG2Runtime(
            True,
            version,
            f"AG2 {version} installed; Gemini synthesis unavailable (missing key)",
            agents,
            llm_model=model,
            status="missing_key",
        )

    return AG2Runtime(True, version, f"AG2 {version} + Gemini {model}", agents, True, model, "ready")


def analyze_fixture(fixture_id: str = "clean", field_domain: str | None = None) -> dict[str, Any]:
    text, fixture_meta = load_fixture_text(fixture_id)
    return analyze_text(text, source=f"sample_fixture:{fixture_meta['fixture_id']}", fixture_meta=fixture_meta, field_domain=field_domain)


def analyze_text(
    text: str,
    source: str,
    fixture_meta: dict[str, Any] | None = None,
    field_domain: str | None = None,
) -> dict[str, Any]:
    runtime = detect_ag2_runtime()
    fixture_meta = fixture_meta or {"fixture_id": "uploaded", **FIXTURES["clean"]}
    paper = parse_manuscript_text(text, source=source)
    if field_domain:
        paper["field_guess"] = field_domain

    board = build_empty_board(
        paper,
        {
            "workflow_engine": runtime.label,
            "sandbox_provider": "Daytona",
            "llm_provider": "OpenAI",
            "llm_model": DEFAULT_OPENAI_MODEL,
            "fixture_id": fixture_meta.get("fixture_id"),
            "ag2_status": runtime.status,
            "ag2_model": runtime.llm_model,
        },
    )

    _run_step(board, "intake_agent", "Extract paper profile and atomic claims", lambda: _intake(board, paper))
    _run_step(board, "methods_statistics_agent", "Assess methodology and statistics risk", lambda: _methods_stats(board, paper))
    _run_step(board, "integrity_agent", "Scan manuscript for prompt-injection and suspicious instructions", lambda: _integrity(board, paper))
    _run_step(board, "novelty_literature_agent", "Attach lightweight related-work risks", lambda: _novelty(board, paper))
    _run_step(
        board,
        "reproducibility_agent",
        "Run Daytona sandbox with OpenAI GPT-5.5 as reproducibility agent",
        lambda: _reproducibility(board, paper, fixture_meta),
    )
    _run_step(board, "area_chair_agent", _area_chair_label(runtime), lambda: _area_chair(board, runtime))

    return board


def _run_step(board: dict[str, Any], agent: str, label: str, fn) -> None:
    started = datetime.now(timezone.utc).isoformat()
    trace = {"agent": agent, "label": label, "status": "running", "started_at": started}
    board["agent_trace"].append(trace)
    try:
        fn()
        trace["status"] = "complete"
    except Exception as exc:
        trace["status"] = "error"
        trace["error"] = str(exc)
        board["concerns"].append(
            {
                "id": _next_id(board, "concern"),
                "agent": agent,
                "severity": "high",
                "category": "workflow",
                "text": f"{label} failed: {exc}",
                "human_followup": "Rerun this agent after checking environment configuration.",
            }
        )
    finally:
        trace["completed_at"] = datetime.now(timezone.utc).isoformat()


def _intake(board: dict[str, Any], paper: dict[str, Any]) -> None:
    for idx, claim in enumerate(paper["claims"], start=1):
        claim_id = f"claim_{idx:03d}"
        evidence_id = f"ev_{idx:03d}"
        claim_type = _claim_type(claim)
        board["claims"].append(
            {
                "id": claim_id,
                "text": claim,
                "type": claim_type,
                "supporting_evidence_ids": [evidence_id],
                "concern_ids": [],
            }
        )
        board["evidence"].append(
            {
                "id": evidence_id,
                "claim_id": claim_id,
                "source_location": "abstract/results",
                "text": _evidence_for_claim(claim, paper),
            }
        )


def _methods_stats(board: dict[str, Any], paper: dict[str, Any]) -> None:
    text = paper["raw_text"].lower()
    checks = []
    has_clear_split = "train/validation/test" in text or ("train" in text and "validation" in text and "test" in text)

    if "does not clearly separate train and test" in text or not has_clear_split:
        checks.append(("high", "methods", "Train/test split is unclear or absent.", "Ask authors for exact split construction."))
    if "does not describe a baseline" in text or "baseline" not in text:
        checks.append(("high", "methods", "Baseline comparison appears underspecified.", "Ask authors for baseline code and hyperparameters."))
    if "small pilot" in text or "48 patient" in text:
        checks.append(("high", "stats", "Sample size is too small for broad deployment claims.", "Ask authors for external validation or narrower claims."))
    if "proves causal" in text or ("causal" in text and "observational" in text):
        checks.append(("high", "stats", "Causal language is unsupported by observational evidence.", "Ask authors to revise causal claims or add identification assumptions."))
    if "ablation" not in text:
        checks.append(("medium", "methods", "Ablation evidence is missing or thin.", "Ask authors which components drive the gain."))

    if not checks:
        checks.append(
            (
                "low",
                "methods",
                "Core split and baseline details are present for a first-pass review.",
                "Human reviewer should still inspect fixture representativeness.",
            )
        )

    for severity, category, concern, followup in checks[:5]:
        _append_concern(
            board,
            "methods_statistics_agent",
            severity,
            category,
            concern,
            followup,
            claim_ids=_claim_ids_for_concern(board, category, concern),
        )


def _integrity(board: dict[str, Any], paper: dict[str, Any]) -> None:
    findings = scan_for_prompt_injection(paper["raw_text"])
    for finding in findings:
        _append_concern(
            board,
            "integrity_agent",
            finding["severity"],
            "integrity",
            f"{finding['finding']} Matched text: {finding['matched_text']!r}.",
            finding["recommendation"],
        )

    if not findings:
        board["concerns"].append(
            {
                "id": _next_id(board, "concern"),
                "agent": "integrity_agent",
                "severity": "low",
                "category": "integrity",
                "text": "No prompt-injection phrases were found by the regex scanner.",
                "human_followup": "Continue to treat raw manuscript text as untrusted input.",
            }
        )


def _novelty(board: dict[str, Any], paper: dict[str, Any]) -> None:
    related = get_related_work(paper["field_guess"], paper["title"])
    board["related_work"] = related
    for paper_ref in related:
        if paper_ref["novelty_risk"] == "high":
            _append_concern(
                board,
                "novelty_literature_agent",
                "medium",
                "novelty",
                f"Potential novelty overlap: {paper_ref['title']}.",
                paper_ref["reason"],
                claim_ids=_claim_ids_matching(board, ["prior", "baseline", "method", "outperform", "obsolete"]),
            )


def _reproducibility(board: dict[str, Any], paper: dict[str, Any], fixture_meta: dict[str, Any]) -> None:
    receipt = DaytonaOpenAIReproRunner().run(fixture_meta, paper)
    board["repro_checks"].append(receipt)

    status = receipt.get("status")
    if status in {"failed", "inconclusive"}:
        severity = "high" if status == "failed" else "medium"
        _append_concern(
            board,
            "reproducibility_agent",
            severity,
            "reproducibility",
            f"Reproducibility probe was {status}: reported {receipt.get('reported_result')} vs observed {receipt.get('observed_result')}.",
            receipt.get("human_followup", "Ask authors for executable artifacts."),
            claim_ids=_metric_claim_ids(board),
        )


def _area_chair(board: dict[str, Any], runtime: AG2Runtime) -> None:
    recommendation = _triage_recommendation(board)
    expertise = _recommended_expertise(board)
    synthesis = None

    if runtime.llm_enabled:
        try:
            synthesis = _ag2_area_chair_synthesis(board, recommendation, expertise, runtime)
            board["metadata"]["ag2_status"] = "used"
        except Exception as exc:
            board["metadata"]["ag2_status"] = "error"
            board["metadata"]["ag2_error"] = str(exc)[:500]
            _append_concern(
                board,
                "area_chair_agent",
                "high",
                "workflow",
                f"AG2/Gemini area-chair synthesis failed: {exc}",
                "Check AG2/Gemini configuration before the live demo or use deterministic fallback.",
                claim_ids=[],
            )
            recommendation = _triage_recommendation(board)
    else:
        board["metadata"]["ag2_status"] = runtime.status
        if runtime.error:
            board["metadata"]["ag2_error"] = runtime.error[:500]

    markdown = _packet_markdown(board, recommendation, expertise, synthesis)
    board["final_packet"] = {
        "triage_recommendation": recommendation,
        "recommended_human_reviewer_expertise": expertise,
        "markdown": markdown,
        "area_chair_synthesis": synthesis,
        "ethical_boundary": "RefereeOS prepares human peer review and does not make publication decisions.",
    }


def _triage_recommendation(board: dict[str, Any]) -> str:
    high_categories = {concern["category"] for concern in board["concerns"] if concern["severity"] == "high"}
    repro_statuses = {check.get("status") for check in board["repro_checks"]}

    if "integrity" in high_categories:
        return "Possible integrity issue"
    if "failed" in repro_statuses or "inconclusive" in repro_statuses:
        return "Reproducibility check failed or inconclusive"
    if "workflow" in high_categories:
        return "Needs author clarification before review"
    if high_categories.intersection({"methods", "stats", "novelty"}):
        return "Needs author clarification before review"
    return "Ready for human review"


def _recommended_expertise(board: dict[str, Any]) -> list[str]:
    field = board["paper"]["field_guess"]
    expertise = [field.title(), "Reproducible computational methods"]
    if any(concern["category"] == "stats" for concern in board["concerns"]):
        expertise.append("Statistical validation")
    if any(concern["category"] == "integrity" and concern["severity"] == "high" for concern in board["concerns"]):
        expertise.append("Research integrity / adversarial ML review")
    return expertise


def _packet_markdown(
    board: dict[str, Any],
    recommendation: str,
    expertise: list[str],
    synthesis: dict[str, str] | None = None,
) -> str:
    paper = board["paper"]
    claims = "\n".join(f"{idx}. {claim['text']}" for idx, claim in enumerate(board["claims"], start=1))
    evidence_rows = "\n".join(
        f"| {claim['id']} | {claim['text']} | {', '.join(claim['concern_ids']) or 'No direct concern'} |"
        for claim in board["claims"]
    )
    concern_lines = "\n".join(
        f"- **{concern['severity'].title()} {concern['category']}**: {concern['text']} Follow-up: {concern['human_followup']}"
        for concern in board["concerns"]
    )
    related_lines = "\n".join(
        f"- {item['title']} ({item['novelty_risk']} risk): {item['reason']}" for item in board["related_work"]
    )
    repro = board["repro_checks"][0] if board["repro_checks"] else {}
    expertise_lines = "\n".join(f"- {item}" for item in expertise)
    synthesis_section = ""
    if synthesis:
        summary = synthesis.get("summary", "").strip()
        risk_summary = synthesis.get("risk_summary", "").strip()
        human_focus = synthesis.get("human_focus", "").strip()
        synthesis_lines = "\n".join(line for line in [summary, risk_summary, human_focus] if line)
        synthesis_section = f"""
## AG2 Area Chair Synthesis
{synthesis_lines}
"""

    return f"""# RefereeOS Reviewer Packet

## Triage Recommendation
{recommendation}

## Paper Summary
**Title:** {paper['title']}

**Field guess:** {paper['field_guess']}

{paper['abstract']}

## Top Claims
{claims}

## Evidence Map
| Claim ID | Claim | Concern Links |
|---|---|---|
{evidence_rows}

## Methodological, Integrity, And Novelty Risks
{concern_lines}

## Related Work / Novelty Risks
{related_lines}
{synthesis_section}

## Reproducibility Receipt
- Sandbox: {repro.get('sandbox_provider', 'Daytona')}
- Model: {repro.get('model', DEFAULT_OPENAI_MODEL)}
- Probe: {repro.get('probe', 'Not run')}
- Status: {repro.get('status', 'not_run')}
- Commands run: {', '.join(repro.get('commands_run', [])) or 'None'}
- Reported result: {repro.get('reported_result', 'unknown')}
- Observed result: {repro.get('observed_result', 'unknown')}
- LLM interpretation: {repro.get('llm_interpretation', 'No interpretation available')}
- Human follow-up: {repro.get('human_followup', 'Human review required')}

## Recommended Human Reviewer Expertise
{expertise_lines}

## Human Judgment Still Required
RefereeOS prepares peer review. It does not make final publication accept/reject decisions.
"""


def _append_concern(
    board: dict[str, Any],
    agent: str,
    severity: str,
    category: str,
    text: str,
    human_followup: str,
    claim_ids: list[str] | None = None,
) -> None:
    concern_id = _next_id(board, "concern")
    board["concerns"].append(
        {
            "id": concern_id,
            "agent": agent,
            "severity": severity,
            "category": category,
            "text": text,
            "human_followup": human_followup,
        }
    )
    linked_claim_ids = set(claim_ids or [])
    for claim in board["claims"]:
        if claim["id"] in linked_claim_ids and concern_id not in claim["concern_ids"]:
            claim["concern_ids"].append(concern_id)


def _area_chair_label(runtime: AG2Runtime) -> str:
    if runtime.llm_enabled:
        return f"Synthesize reviewer-prep packet with {runtime.label}"
    return "Synthesize reviewer-prep packet with deterministic fallback"


def _ag2_area_chair_synthesis(
    board: dict[str, Any],
    recommendation: str,
    expertise: list[str],
    runtime: AG2Runtime,
) -> dict[str, str]:
    """Area-chair synthesis using AG2 Beta agents with agent-as-tool collaboration.

    Uses autogen.beta.Agent for the area_chair and method_critic, with
    method_critic exposed as a tool to area_chair (agent-as-tool pattern).
    Falls back to legacy ConversableAgent if autogen.beta is unavailable.
    """
    import asyncio
    import json as _json

    llm_config = _build_llm_config(runtime)
    if llm_config is None:
        raise RuntimeError("No LLM API key configured (Gemini or DeepSeek)")

    prompt = _area_chair_prompt(board, recommendation, expertise)

    try:
        return asyncio.get_event_loop().run_until_complete(_beta_synthesis(prompt, llm_config))
    except RuntimeError:
        return asyncio.run(_beta_synthesis(prompt, llm_config))


def _build_llm_config(runtime: AG2Runtime) -> dict[str, str] | None:
    """Build LLM config dict. Prefers Gemini, falls back to DeepSeek."""
    gemini_key = _gemini_api_key()
    if gemini_key:
        return {
            "model": runtime.llm_model or os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview"),
            "api_key": gemini_key,
            "api_type": "google",
            "base_url": "",
        }
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key:
        return {
            "model": os.getenv("AG2_MODEL", "deepseek-v4-pro"),
            "api_key": deepseek_key,
            "api_type": "openai",
            "base_url": os.getenv("AG2_BASE_URL", "https://api.deepseek.com/v1"),
        }
    return None


async def _beta_synthesis(prompt: str, llm_config: dict[str, str]) -> dict[str, str]:
    """Run area-chair synthesis with AG2 Beta agent-as-tool pattern."""
    from autogen.beta import Agent  # type: ignore
    from autogen.beta.config import OpenAIConfig, GeminiConfig  # type: ignore

    api_type = llm_config.get("api_type", "openai")
    model = llm_config["model"]
    api_key = llm_config["api_key"]
    base_url = llm_config.get("base_url", "")

    if api_type == "google":
        config = GeminiConfig(model=model, api_key=api_key, temperature=0)
    else:
        config = OpenAIConfig(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=0,
            extra_body={"thinking": {"type": "disabled"}} if "deepseek" in model.lower() else {},
        )

    # Method critic agent -- exposed as a tool to area_chair
    method_critic = Agent(
        "method_critic",
        prompt=(
            "You are a rigorous methodology critic for scientific peer review. "
            "Given the review evidence, identify the top methodological weakness. "
            "Output exactly ONE concern in 2-3 sentences. Focus on statistical, "
            "experimental design, or reproducibility issues."
        ),
        config=config,
    )

    # Area chair agent -- uses method_critic as a tool
    area_chair = Agent(
        "area_chair",
        prompt=(
            "You are the RefereeOS area chair synthesis agent. "
            "Summarize review-prep evidence for a human editor. "
            "First, use the 'critique_methods' tool to get methodology feedback. "
            "Then produce a JSON response with keys: summary, risk_summary, human_focus. "
            "Do NOT recommend accepting or rejecting publication. "
            "Do NOT include accept/reject language."
        ),
        config=config,
    )

    critique_tool = method_critic.as_tool(
        name="critique_methods",
        description="Submit review evidence to the method critic. Returns a focused methodological weakness.",
    )
    area_chair.tools.add(critique_tool)

    reply = await area_chair.ask(prompt)
    text = reply.body.strip() if hasattr(reply, "body") else str(reply).strip()
    return _parse_synthesis(text, model)


def _parse_synthesis(text: str, model: str) -> dict[str, str]:
    """Parse synthesis output into structured dict."""
    parsed = _parse_json_object(text)
    if parsed:
        return {
            "source": f"AG2 Beta + {model}",
            "summary": str(parsed.get("summary", "")).strip(),
            "risk_summary": str(parsed.get("risk_summary", "")).strip(),
            "human_focus": str(parsed.get("human_focus", "")).strip(),
        }
    return {
        "source": f"AG2 Beta + {model}",
        "summary": text[:1200],
        "risk_summary": "",
        "human_focus": "",
    }


def _area_chair_prompt(board: dict[str, Any], recommendation: str, expertise: list[str]) -> str:
    digest = {
        "paper": board["paper"],
        "claims": board["claims"],
        "concerns": board["concerns"],
        "repro_checks": board["repro_checks"],
        "deterministic_triage_recommendation": recommendation,
        "recommended_human_reviewer_expertise": expertise,
    }
    return (
        "Return JSON only with keys summary, risk_summary, and human_focus. "
        "Preserve the deterministic triage recommendation and do not include accept/reject language.\n\n"
        + json.dumps(digest, indent=2)
    )


def _reply_to_text(reply: Any) -> str:
    if isinstance(reply, str):
        return reply.strip()
    if isinstance(reply, dict):
        return str(reply.get("content") or reply.get("text") or reply).strip()
    return str(reply).strip()


def _parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _gemini_api_key() -> str:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""


def _claim_ids_for_concern(board: dict[str, Any], category: str, concern_text: str) -> list[str]:
    lowered = concern_text.lower()
    if category == "stats":
        if "causal" in lowered:
            return _claim_ids_matching(board, ["causal", "deploy", "hospital", "clinical"])
        if "sample size" in lowered:
            return _claim_ids_matching(board, ["deploy", "hospital", "clinical", "causal"])
    if category == "methods":
        if "baseline" in lowered or "train/test" in lowered:
            return _metric_claim_ids(board)
        if "ablation" in lowered:
            return _claim_ids_matching(board, ["feature", "method", "component"])
    return []


def _metric_claim_ids(board: dict[str, Any]) -> list[str]:
    return _claim_ids_matching(board, ["macro f1", "f1", "metric", "benchmark", "reported"])


def _claim_ids_matching(board: dict[str, Any], keywords: list[str]) -> list[str]:
    matches = []
    for claim in board["claims"]:
        text = claim["text"].lower()
        if any(keyword in text for keyword in keywords):
            matches.append(claim["id"])
    return matches


def _next_id(board: dict[str, Any], prefix: str) -> str:
    existing = len(board["concerns"]) + 1 if prefix == "concern" else 1
    return f"{prefix}_{existing:03d}"


def _claim_type(claim: str) -> str:
    lowered = claim.lower()
    if "causal" in lowered or "proves" in lowered:
        return "causal"
    if "f1" in lowered or "benchmark" in lowered or "outperform" in lowered:
        return "benchmark"
    if "method" in lowered or "feature" in lowered:
        return "methodological"
    return "empirical"


def _evidence_for_claim(claim: str, paper: dict[str, Any]) -> str:
    if "f1" in claim.lower():
        return paper.get("results_summary") or paper.get("abstract")
    return paper.get("abstract")

"""AG2 Beta multi-agent peer review pipeline.

Upgraded version that integrates with RefereeOS's paper_parser and
evidence_board modules. Accepts the same inputs as the main orchestrator
(paper text, fixture files, or PDF paths) and produces a structured
evidence board with Beta-agent-driven methodology critique.

Run standalone:
    python ag2_reviewer.py                          # uses sample paper
    python ag2_reviewer.py --fixture suspicious     # uses suspicious paper
    python ag2_reviewer.py --text "paper text..."   # uses custom text

When REFEREEOS_ENABLE_AG2_LLM=true and an API key is set, this pipeline
is also called by orchestrator.py's area_chair step via
_ag2_area_chair_synthesis().
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project root is on sys.path so backend.* imports work
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv  # type: ignore

load_dotenv()

# ---------------------------------------------------------------------------
# AG2 Beta agents
# ---------------------------------------------------------------------------
from autogen.beta import Agent  # type: ignore
from autogen.beta.config import OpenAIConfig, GeminiConfig  # type: ignore

# ---------------------------------------------------------------------------
# RefereeOS modules (paper parsing + evidence board)
# ---------------------------------------------------------------------------
from backend.parsing.paper_parser import (
    parse_manuscript_text,
    load_fixture_text,
)
from backend.storage.evidence_board import build_empty_board


# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------
def _build_config() -> OpenAIConfig | GeminiConfig:
    """Build AG2 Beta LLM config. Prefers Gemini, falls back to DeepSeek."""
    gemini_key = (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )
    if gemini_key:
        model = os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")
        return GeminiConfig(model=model, api_key=gemini_key, temperature=0)

    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key:
        model = os.getenv("AG2_MODEL", "deepseek-v4-pro")
        base_url = os.getenv("AG2_BASE_URL", "https://api.deepseek.com/v1")
        return OpenAIConfig(
            model=model,
            api_key=deepseek_key,
            base_url=base_url,
            temperature=0.2,
            extra_body={"thinking": {"type": "disabled"}}
            if "deepseek" in model.lower()
            else {},
        )

    raise SystemExit(
        "ERROR: No LLM API key found. Set DEEPSEEK_API_KEY or GEMINI_API_KEY in .env"
    )


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------
def create_agents(config: OpenAIConfig | GeminiConfig) -> tuple[Agent, Agent, Agent]:
    """Create the three Beta agents: claim_extractor, method_critic, area_chair."""

    claim_extractor = Agent(
        "claim_extractor",
        prompt=(
            "You extract scientific claims from academic papers. "
            "For each claim, provide: (1) the claim text, (2) claim type "
            "(empirical / theoretical / methodological / benchmark / causal), "
            "(3) confidence 0-1. Output as a numbered list. Be concise."
        ),
        config=config,
    )

    method_critic = Agent(
        "method_critic",
        prompt=(
            "You are a rigorous methodology critic for scientific peer review. "
            "Given a scientific claim and its context, identify the SINGLE most "
            "important methodological weakness: statistical, experimental design, "
            "reproducibility, or data concern. Be concrete and specific. "
            "Output exactly ONE concern in 2-3 sentences."
        ),
        config=config,
    )

    area_chair = Agent(
        "area_chair",
        prompt=(
            "You are an AREA CHAIR synthesizing a structured peer review. "
            "You will receive extracted claims and should use the 'critique_method' "
            "tool to ask method_critic about each major claim. "
            "After collecting critiques, produce a structured review with:\n"
            "## Summary\n## Major Concerns\n## Minor Issues\n"
            "## Verdict (Accept / Minor Revision / Major Revision / Reject)\n\n"
            "Do NOT make final publication accept/reject decisions. "
            "Frame the verdict as a recommendation for human reviewers."
        ),
        config=config,
    )

    # Agent-as-tool: expose method_critic as a callable tool for area_chair
    critique_tool = method_critic.as_tool(
        name="critique_method",
        description=(
            "Submit a scientific claim to the method critic. "
            "Returns ONE specific methodological weakness analysis."
        ),
    )
    area_chair.tools.add(critique_tool)

    return claim_extractor, method_critic, area_chair


# ---------------------------------------------------------------------------
# Review pipeline
# ---------------------------------------------------------------------------
async def review_paper(
    paper_text: str,
    source: str = "uploaded",
    fixture_meta: dict | None = None,
) -> dict:
    """Run the full AG2 Beta review pipeline on paper text.

    Returns an evidence-board dict compatible with the main orchestrator.
    """
    config = _build_config()
    claim_extractor, method_critic, area_chair = create_agents(config)

    # Parse paper using RefereeOS's paper_parser
    fixture_meta = fixture_meta or {
        "fixture_id": "beta_review",
        "reported_result": None,
        "expected_status": "reviewed",
    }
    paper = parse_manuscript_text(paper_text, source=source)

    # Build evidence board using RefereeOS's storage module
    board = build_empty_board(
        paper,
        {
            "workflow_engine": "AG2 Beta (autogen.beta.Agent)",
            "sandbox_provider": "Daytona (optional)",
            "llm_provider": "DeepSeek" if os.getenv("DEEPSEEK_API_KEY") else "Gemini",
            "llm_model": os.getenv("AG2_MODEL", os.getenv("GEMINI_MODEL", "unknown")),
            "fixture_id": fixture_meta.get("fixture_id"),
            "ag2_status": "beta_active",
        },
    )

    # --- Step 1: Extract claims ---
    print("  [1/3] Extracting claims via claim_extractor agent...")
    claims_reply = await claim_extractor.ask(
        f"Extract all main scientific claims from this paper:\n\n{paper_text[:4000]}"
    )
    claims_text = claims_reply.body if hasattr(claims_reply, "body") else str(claims_reply)

    # Populate evidence board claims
    for idx, line in enumerate(claims_text.splitlines(), start=1):
        line = line.strip().lstrip("0123456789.-) ")
        if len(line) < 15:
            continue
        claim_id = f"claim_{idx:03d}"
        evidence_id = f"ev_{idx:03d}"
        board["claims"].append(
            {
                "id": claim_id,
                "text": line,
                "type": _guess_claim_type(line),
                "supporting_evidence_ids": [evidence_id],
                "concern_ids": [],
            }
        )
        board["evidence"].append(
            {
                "id": evidence_id,
                "claim_id": claim_id,
                "source_location": "abstract/results",
                "text": paper.get("abstract", "")[:300],
            }
        )

    # Record agent trace
    board["agent_trace"].append(
        {
            "agent": "claim_extractor",
            "label": "Extract paper profile and scientific claims (AG2 Beta)",
            "status": "complete",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    # --- Step 2: Area chair synthesis (calls method_critic via tool) ---
    print("  [2/3] Synthesizing review via area_chair + method_critic (agent-as-tool)...")
    final_reply = await area_chair.ask(
        f"Paper title: {paper['title']}\n\n"
        f"Claims:\n{claims_text}\n\n"
        f"Abstract: {paper.get('abstract', '')[:600]}\n\n"
        f"Please produce the full structured peer review."
    )
    review_text = final_reply.body if hasattr(final_reply, "body") else str(final_reply)

    board["agent_trace"].append(
        {
            "agent": "area_chair",
            "label": "Synthesize review with method_critic tool (AG2 Beta agent-as-tool)",
            "status": "complete",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    # --- Step 3: Build final packet ---
    print("  [3/3] Building reviewer packet...")

    # Extract structured sections from the review text
    concerns = _extract_concerns(review_text)
    for idx, (severity, category, text) in enumerate(concerns):
        concern_id = f"concern_{idx + 1:03d}"
        board["concerns"].append(
            {
                "id": concern_id,
                "agent": "method_critic",
                "severity": severity,
                "category": category,
                "text": text,
                "human_followup": f"Reviewer should verify: {text[:100]}",
            }
        )

    board["final_packet"] = {
        "triage_recommendation": _extract_verdict(review_text),
        "recommended_human_reviewer_expertise": [
            paper.get("field_guess", "computational science").title(),
            "Reproducible computational methods",
        ],
        "markdown": review_text,
        "area_chair_synthesis": {
            "source": "AG2 Beta pipeline",
            "summary": review_text[:500],
        },
        "ethical_boundary": (
            "RefereeOS prepares human peer review and does not make publication decisions."
        ),
    }

    return board


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _guess_claim_type(text: str) -> str:
    lowered = text.lower()
    if "causal" in lowered or "proves" in lowered:
        return "causal"
    if "f1" in lowered or "benchmark" in lowered or "outperform" in lowered:
        return "benchmark"
    if "method" in lowered or "feature" in lowered:
        return "methodological"
    return "empirical"


def _extract_concerns(text: str) -> list[tuple[str, str, str]]:
    """Extract concerns from review text. Returns list of (severity, category, text)."""
    concerns = []
    # Look for Major Concerns section
    if "Major Concerns" in text:
        section = text.split("Major Concerns")[-1].split("##")[0]
        for line in section.strip().splitlines():
            line = line.strip().lstrip("-*0123456789. ")
            if len(line) > 20:
                concerns.append(("high", "methods", line))
    if "Minor Issues" in text:
        section = text.split("Minor Issues")[-1].split("##")[0]
        for line in section.strip().splitlines():
            line = line.strip().lstrip("-*0123456789. ")
            if len(line) > 20:
                concerns.append(("medium", "methods", line))
    return concerns[:5]


def _extract_verdict(text: str) -> str:
    """Extract verdict from review text."""
    lowered = text.lower()
    for keyword, verdict in [
        ("reject", "Needs major revision or rejection"),
        ("major revision", "Needs major revision before review"),
        ("minor revision", "Minor revision recommended"),
        ("accept", "Ready for human review"),
    ]:
        if keyword in lowered:
            return verdict
    return "Needs author clarification before review"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AG2 Beta peer review pipeline")
    parser.add_argument("--fixture", default="clean", help="Fixture ID (clean or suspicious)")
    parser.add_argument("--text", default=None, help="Custom paper text")
    args = parser.parse_args()

    if args.text:
        paper_text = args.text
        source = "cli_arg"
        fixture_meta = {"fixture_id": "custom", "reported_result": None}
    else:
        paper_text, fixture_meta = load_fixture_text(args.fixture)
        source = f"fixture:{args.fixture}"

    print(f"\n{'=' * 60}")
    print(f"  AG2 Beta Peer Review Pipeline")
    print(f"  Source: {source}")
    print(f"{'=' * 60}\n")

    board = asyncio.run(review_paper(paper_text, source=source, fixture_meta=fixture_meta))

    # Print structured output
    print(f"\n{'=' * 60}")
    print("  EVIDENCE BOARD SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Claims:    {len(board['claims'])}")
    print(f"  Evidence:  {len(board['evidence'])}")
    print(f"  Concerns:  {len(board['concerns'])}")
    print(f"  Triage:    {board['final_packet']['triage_recommendation']}")
    print(f"  Engine:    {board['metadata']['workflow_engine']}")
    print(f"\n{'=' * 60}")
    print("  FINAL REVIEW")
    print(f"{'=' * 60}\n")
    print(board["final_packet"]["markdown"])

    # Save evidence board as JSON
    output_dir = Path("outputs/beta_runs")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"beta_{fixture_meta.get('fixture_id', 'run')}.json"
    output_path.write_text(json.dumps(board, indent=2, default=str), encoding="utf-8")
    print(f"\n  Evidence board saved to: {output_path}")

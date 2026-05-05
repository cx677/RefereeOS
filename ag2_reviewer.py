"""AG2 Beta multi-agent peer review pipeline.

Upgraded version that integrates with RefereeOS's paper_parser and
evidence_board modules. Accepts the same inputs as the main orchestrator
(paper text, fixture files, or PDF paths) and produces a structured
evidence board with Beta-agent-driven methodology critique.

Run standalone:
    python ag2_reviewer.py                          # uses sample paper
    python ag2_reviewer.py --fixture suspicious     # uses suspicious paper
    python ag2_reviewer.py --text "paper text..."   # uses custom text

Note: ``orchestrator.py`` calls :func:`_ag2_area_chair_synthesis`
which runs its own Beta-agent synthesis via
:func:`backend.agents.agent_factory.create_agents_for_synthesis`.
This CLI entry point uses
:func:`backend.agents.agent_factory.create_agents_for_pipeline`
for the three-agent (claim extractor + method critic + area chair) pipeline.
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
# AG2 Beta agents (lazy import -- only loaded when API keys are available)
# ---------------------------------------------------------------------------

try:
    from autogen.beta import Agent  # type: ignore
    from autogen.beta.config import OpenAIConfig, GeminiConfig  # type: ignore
except ImportError:
    Agent = None  # type: ignore[assignment,misc]
    OpenAIConfig = None  # type: ignore[assignment,misc]
    GeminiConfig = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# RefereeOS modules (paper parsing + evidence board)
# ---------------------------------------------------------------------------
from backend.parsing.paper_parser import (
    parse_manuscript_text,
    load_fixture_text,
)
from backend.storage.evidence_board import build_empty_board
from backend.config import build_llm_config, classify_claim


# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------
def _build_config():
    """Build AG2 Beta LLM config using shared config module."""
    return build_llm_config(temperature=0.2)


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------
def create_agents(config) -> tuple:
    """Create the three Beta agents via shared factory.

    Delegates to :func:`backend.agents.agent_factory.create_agents_for_pipeline`
    so that prompts and tool names stay in sync with ``orchestrator.py``.
    The tool is registered as ``critique_methods`` (plural) consistently.
    """
    from backend.agents.agent_factory import create_agents_for_pipeline
    return create_agents_for_pipeline(config)


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
    try:
        claims_reply = await claim_extractor.ask(
            f"Extract all main scientific claims from this paper:\n\n{paper_text[:4000]}"
        )
        claims_text = claims_reply.body if hasattr(claims_reply, "body") else str(claims_reply)
    except Exception as exc:
        print(f"  [1/3] claim_extractor failed: {exc}")
        board["agent_trace"].append(
            {
                "agent": "claim_extractor",
                "label": "Extract paper profile and scientific claims (AG2 Beta)",
                "status": "error",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc)[:500],
            }
        )
        board["concerns"].append(
            {
                "id": "concern_001",
                "agent": "claim_extractor",
                "severity": "high",
                "category": "workflow",
                "text": f"Claim extraction failed: {exc}",
                "human_followup": "Check API key and network connectivity, then rerun.",
            }
        )
        board["final_packet"] = {
            "triage_recommendation": "Needs author clarification before review",
            "recommended_human_reviewer_expertise": [paper.get("field_guess", "computational science").title()],
            "markdown": f"Claim extraction failed: {exc}",
            "area_chair_synthesis": {"source": "error", "summary": str(exc)[:500]},
            "ethical_boundary": "RefereeOS prepares human peer review and does not make publication decisions.",
        }
        return board

    # Populate evidence board claims
    claim_counter = 0
    for raw_line in claims_text.splitlines():
        line = raw_line.strip().lstrip("0123456789.-) ")
        # Skip headings, separator lines, and short lines
        if not line or line.startswith("#") or line.startswith("---") or len(line) < 15:
            continue
        claim_counter += 1
        claim_id = f"claim_{claim_counter:03d}"
        evidence_id = f"ev_{claim_counter:03d}"
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
    try:
        final_reply = await area_chair.ask(
            f"Paper title: {paper['title']}\n\n"
            f"Claims:\n{claims_text}\n\n"
            f"Abstract: {paper.get('abstract', '')[:600]}\n\n"
            f"Please produce the full structured peer review."
        )
        review_text = final_reply.body if hasattr(final_reply, "body") else str(final_reply)
    except Exception as exc:
        print(f"  [2/3] area_chair synthesis failed: {exc}")
        board["agent_trace"].append(
            {
                "agent": "area_chair",
                "label": "Synthesize review with method_critic tool (AG2 Beta agent-as-tool)",
                "status": "error",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc)[:500],
            }
        )
        board["concerns"].append(
            {
                "id": f"concern_{len(board['concerns']) + 1:03d}",
                "agent": "area_chair",
                "severity": "high",
                "category": "workflow",
                "text": f"Area-chair synthesis failed: {exc}",
                "human_followup": "Check API key and rate limits, then rerun.",
            }
        )
        board["final_packet"] = {
            "triage_recommendation": "Needs author clarification before review",
            "recommended_human_reviewer_expertise": [paper.get("field_guess", "computational science").title()],
            "markdown": f"Area-chair synthesis failed: {exc}",
            "area_chair_synthesis": {"source": "error", "summary": str(exc)[:500]},
            "ethical_boundary": "RefereeOS prepares human peer review and does not make publication decisions.",
        }
        return board

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
    """Delegate to shared classify_claim for word-boundary matching."""
    return classify_claim(text)


def _extract_concerns(text: str) -> list[tuple[str, str, str]]:
    """Extract concerns from review text. Returns list of (severity, category, text).

    Infers category from section headers when available instead of
    hardcoding everything to 'methods'.
    """
    concerns: list[tuple[str, str, str]] = []

    # Map section headers to (severity, category)
    section_map = [
        ("Major Concerns", "high", None),
        ("Integrity Concerns", "high", "integrity"),
        ("Novelty Concerns", "medium", "novelty"),
        ("Statistical Concerns", "high", "statistics"),
        ("Minor Issues", "medium", None),
    ]

    for header, severity, explicit_category in section_map:
        if header not in text:
            continue
        section = text.split(header)[-1].split("##")[0]
        for line in section.strip().splitlines():
            line = line.strip().lstrip("-*0123456789. ")
            if len(line) > 20:
                category = explicit_category or "methods"
                concerns.append((severity, category, line))

    return concerns


def _extract_verdict(text: str) -> str:
    """Extract verdict from review text using word-boundary matching."""
    import re as _re

    lowered = text.lower()
    # Check longer phrases first to avoid partial-match false positives
    for pattern, verdict in [
        (_re.compile(r"\bmajor\s+revision\b"), "Needs major revision before review"),
        (_re.compile(r"\bminor\s+revision\b"), "Minor revision recommended"),
        (_re.compile(r"\baccept\b"), "Ready for human review"),
        (_re.compile(r"\breject\b"), "Needs major revision or rejection"),
    ]:
        if pattern.search(lowered):
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

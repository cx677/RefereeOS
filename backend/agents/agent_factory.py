"""Shared agent factory for RefereeOS.

Creates AG2 Beta agents used by both :func:`orchestrator._beta_synthesis`
and :func:`ag2_reviewer.create_agents`.  Keeping agent definitions in one
place avoids prompt/tool-name drift between the two entry points.
"""

from __future__ import annotations

from autogen.beta import Agent  # type: ignore


def build_claim_extractor(config) -> Agent:
    """Build the claim-extractor agent."""
    return Agent(
        name="claim_extractor",
        system_prompt=(
            "You are a scientific-claim extraction agent for peer review. "
            "Given a paper excerpt, extract ALL main scientific claims. "
            "Output ONE claim per line, each starting with 'Claim N:'. "
            "Be comprehensive — capture every verifiable claim."
        ),
        llm_config=config,
    )


def build_method_critic(config) -> Agent:
    """Build the method-critic agent (stateless tool target)."""
    return Agent(
        name="method_critic",
        system_prompt=(
            "You are a rigorous methodology critic for scientific peer review. "
            "Given a scientific claim, identify the TOP methodological weakness "
            "that could invalidate it. Output exactly ONE concern in 2-3 sentences. "
            "Focus on statistical power, experimental design, or reproducibility."
        ),
        llm_config=config,
    )


def build_area_chair(config, critique_tool) -> Agent:
    """Build the area-chair synthesis agent with ``critique_methods`` tool."""
    return Agent(
        name="area_chair",
        system_prompt=(
            "You are the RefereeOS area-chair synthesis agent. "
            "Your job is to prepare a structured evidence summary for a human editor. "
            "First, use the 'critique_methods' tool to collect methodological "
            "feedback on key claims. "
            "Then produce a structured review with:\n"
            "## Summary\n## Major Concerns\n## Minor Issues\n"
            "## Verdict (Accept / Minor Revision / Major Revision / Reject)\n\n"
            "Do NOT make final publication accept/reject decisions. "
            "Frame the verdict as a recommendation for human reviewers."
        ),
        llm_config=config,
    )


def make_critique_tool(method_critic: Agent, name: str = "critique_methods"):
    """Wrap ``method_critic`` as a tool and return it.

    The tool is named ``critique_methods`` (plural) consistently in both
    call-sites so the area-chair prompt matches the registered tool name.
    """
    return method_critic.as_tool(
        name=name,
        description=(
            "Submit a scientific claim to the method critic. "
            "Returns ONE specific methodological weakness analysis."
        ),
    )


def create_agents_for_pipeline(config) -> tuple[Agent, Agent, Agent]:
    """Create ``(claim_extractor, method_critic, area_chair)`` for the
    three-agent review pipeline used by ``ag2_reviewer.py``."""
    claim_extractor = build_claim_extractor(config)
    method_critic = build_method_critic(config)
    tool = make_critique_tool(method_critic)
    area_chair = build_area_chair(config, tool)
    area_chair.tools.add(tool)
    return claim_extractor, method_critic, area_chair


def create_agents_for_synthesis(config) -> tuple[Agent, Agent]:
    """Create ``(method_critic, area_chair)`` for ``_beta_synthesis()``."""
    method_critic = build_method_critic(config)
    tool = make_critique_tool(method_critic)
    area_chair = build_area_chair(config, tool)
    area_chair.tools.add(tool)
    return method_critic, area_chair

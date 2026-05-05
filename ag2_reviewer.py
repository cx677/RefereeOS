import asyncio
import os
from dotenv import load_dotenv # type: ignore
from autogen.beta import Agent # type: ignore
from autogen.beta.config import OpenAIConfig # type: ignore

load_dotenv()

config = OpenAIConfig(
    model="deepseek-v4-pro",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com/v1",
    temperature=0.2,
    extra_body={"thinking": {"type": "disabled"}},   # 禁用思考模式
)
claim_extractor = Agent(
    "claim_extractor",
    prompt="Extract scientific claims from the paper. Output as numbered list. Be concise.",
    config=config,
)

method_critic = Agent(
    "method_critic",
    prompt="Given a claim, identify ONE methodological weakness (statistical, design, or reproducibility). ≤3 sentences.",
    config=config,
)

area_chair = Agent(
    "area_chair",
    prompt=(
        "You synthesize claims and critiques into a structured review. "
        "Use the tool 'get_critique' to ask method_critic. "
        "Output format:\nSummary\nMajor Concerns\nVerdict (Accept/Revise/Reject)"
    ),
    config=config,
)

critique_tool = method_critic.as_tool(
    name="get_critique",
    description="Submit a scientific claim and get methodological weakness analysis.",
)
area_chair.tools.append(critique_tool)

async def review_paper(paper_text: str) -> str:
    print("1. Extracting claims...")
    claims_reply = await claim_extractor.ask(paper_text)
    print("2. Synthesizing review (critic tool will be called automatically)...")
    final_reply = await area_chair.ask(f"Claims:\n{claims_reply.body}\n\nProduce final review.")
    return final_reply.body

if __name__ == "__main__":
    sample = "We tested our cancer detection method on 30 patients and got 94% accuracy."
    result = asyncio.run(review_paper(sample))
    print("\n===== FINAL REVIEW =====\n", result)
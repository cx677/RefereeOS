# ATTRIBUTION.md — C5-AG2 Submission by Jingwen Feng

## 1. Fork source

| | |
|---|---|
| Base project | RefereeOS |
| Base repo URL | https://github.com/VJDiPaola/RefereeOS |
| Base captain | Vincent DiPaola |
| Fork commit SHA | `25da229` (initial fork) |
| My fork | https://github.com/cx677/RefereeOS |

## 2. AG2 documentation references

- `docs.ag2.ai/latest/docs/beta/motivation/` — AG2 Beta motivation and design philosophy
- `docs.ag2.ai/latest/docs/beta/` — Beta agent API reference (`Agent.ask()`, `Agent.as_tool()`)
- AG2 Beta hello-agent example — basic `autogen.beta.Agent` usage pattern
- AG2 Beta agent-as-tool example — `method_critic.as_tool()` pattern

## 3. Code reused from sample repos

| Repo | What was reused | How it was modified |
|------|----------------|-------------------|
| VJDiPaola/RefereeOS | Full project: orchestrator.py, paper_parser.py, evidence_board.py, injection_scan.py, daytona_runner.py, FastAPI backend, React frontend | Upgraded area_chair synthesis to AG2 Beta |
| Get me Up2Date | Parallel research agent pattern inspiration | Adapted for claim_extractor + area_chair pipeline |

## 4. What I added

### 4.1 `ag2_reviewer.py` — Standalone Beta pipeline (NEW FILE, ~200 lines)
- 3 AG2 Beta agents: `claim_extractor`, `method_critic`, `area_chair`
- `agent.as_tool()` pattern: method_critic exposed as tool to area_chair
- Integration with RefereeOS `paper_parser.py` and `evidence_board.py`
- CLI interface: `--fixture clean|suspicious`, `--text "custom paper"`
- JSON evidence board output to `outputs/beta_runs/`

### 4.2 `backend/agents/orchestrator.py` L439-540 — Beta area-chair synthesis (REPLACED)
- **Before:** 30-line function using legacy `autogen.ConversableAgent` with Gemini only
- **After:** 100+ lines using `autogen.beta.Agent` with agent-as-tool collaboration
- New functions: `_beta_synthesis()`, `_build_llm_config()`, `_parse_synthesis()`
- Supports both Gemini and DeepSeek as LLM backends
- method_critic agent created and exposed as tool to area_chair

### 4.3 Configuration changes
- `.env.example` — Added `DEEPSEEK_API_KEY`, `AG2_MODEL`, `AG2_BASE_URL`
- `requirements.txt` — Changed `ag2[gemini]>=0.8.0` to `ag2[openai]>=0.9.0`

### 4.4 Documentation
- `LICENSE` — MIT license file (was missing)
- `README.md` — Full rewrite with Mermaid architecture diagram, agent table, setup instructions, troubleshooting, ethical boundary
- `AI_LOG.md` — 10 iterations with verification steps
- `docs/architecture.md` — Updated to reflect Beta architecture

## 5. License

| Component | License |
|-----------|---------|
| Base repo (RefereeOS) | No explicit license (educational hackathon) |
| My additions | MIT |
| AG2 framework | Apache 2.0 |

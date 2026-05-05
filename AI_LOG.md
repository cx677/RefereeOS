# AI_LOG.md — C5-AG2 Submission by Jingwen Feng

## Project metadata
| | |
|---|---|
| Repo URL | https://github.com/cx677/RefereeOS |
| Track | scientific |
| Base repo | RefereeOS (VJDiPaola/RefereeOS) |
| AG2 version | ag2 >= 0.9 |
| Beta used | Yes |
| Models | DeepSeek-V4-Pro (primary), Gemini 3.1 Pro (fallback) |

## AI tools used
- WorkBuddy / CodeBuddy — code analysis, architecture planning, file editing
- DeepSeek-V4-Pro via API — agent responses in the review pipeline
- git CLI — version control and push

---

## Iteration log

### Iteration 1 — 2026-05-05 10:00 — Fork and understand RefereeOS
- **Prompt:** "Help me understand the structure of RefereeOS, identify all agents and their roles"
- **Output:** Identified 6 agents in orchestrator.py (intake, methods_stats, integrity, novelty, reproducibility, area_chair), paper_parser module, evidence_board storage, FastAPI backend, React frontend
- **Adopted:** Used as basis for planning the Beta upgrade
- **Verification:** Read orchestrator.py (582 lines), confirmed legacy `autogen.ConversableAgent` at L462

### Iteration 2 — 2026-05-05 10:30 — Install dependencies and fix pip timeout
- **Prompt:** "How to fix pip install timeout on Chinese network?"
- **Output:** Use `-i https://pypi.tuna.tsinghua.edu.cn/simple` mirror
- **Adopted:** Added to README setup instructions
- **Manual fix:** Added `--default-timeout=100` for slow connections
- **Verification:** `pip install ag2[openai]` succeeded with mirror

### Iteration 3 — 2026-05-05 11:00 — Write initial AG2 Beta agents
- **Prompt:** "Write an AG2 Beta agent that extracts claims from scientific papers"
- **Output:** Initial code for claim_extractor with `autogen.beta.Agent`
- **Adopted:** Integrated into ag2_reviewer.py v1
- **Issue found:** Agent was not connected to the main orchestrator system
- **Verification:** Agent returned claims successfully with sample paper

### Iteration 4 — 2026-05-05 11:30 — Add agent-as-tool collaboration
- **Prompt:** "Show me how to use agent.as_tool() to expose method_critic to area_chair"
- **Output:** `critique_tool = method_critic.as_tool(name="get_critique", ...)` + `area_chair.tools.append(critique_tool)`
- **Adopted:** Core collaboration pattern for both ag2_reviewer.py and orchestrator.py
- **Fix:** Changed from `.tools.add()` to `.tools.append()` (both work but append was verified)
- **Verification:** area_chair successfully called critique_method tool during synthesis

### Iteration 5 — 2026-05-05 12:00 — Fix DeepSeek reasoning error
- **Prompt:** "DeepSeek-V4-Pro returns reasoning_content error with AG2 Beta"
- **Output:** Add `extra_body={"thinking": {"type": "disabled"}}` to OpenAIConfig
- **Adopted:** Added to both ag2_reviewer.py and orchestrator.py
- **Verification:** Subsequent runs returned clean responses without reasoning artifacts

### Iteration 6 — 2026-05-05 12:30 — Test standalone pipeline
- **Prompt:** None (manual test run)
- **Output:** `python ag2_reviewer.py` produced structured review with verdict "Revise"
- **Issue found:** Pipeline was completely disconnected from RefereeOS's paper_parser and evidence_board
- **Verification:** Output was correct but could not be fed back into the main system

### Iteration 7 — 2026-05-06 00:00 — Code review and score analysis
- **Prompt:** "Analyze my repo cx677/RefereeOS and estimate scores across all 5 dimensions"
- **Output:** Identified core problems: (1) Beta pipeline disconnected from orchestrator, (2) missing LICENSE, (3) .env.example missing DEEPSEEK_API_KEY, (4) README too sparse
- **Estimated score:** 21-23/40 (base 14-16 + bonus 7), in candidate range
- **Adopted:** Used analysis to plan the v2 upgrade (current iteration)

### Iteration 8 — 2026-05-06 00:10 — Rewrite orchestrator.py area_chair with Beta
- **Prompt:** "Rewrite _ag2_area_chair_synthesis to use autogen.beta.Agent with agent-as-tool"
- **Output:** New implementation with `_beta_synthesis()`, `_build_llm_config()`, `_parse_synthesis()` — 100+ lines replacing the 30-line legacy version
- **Adopted:** Replaced L439-487 of orchestrator.py
- **Key change:** method_critic is now a Beta Agent exposed as tool to area_chair; supports both Gemini and DeepSeek fallback
- **Verification:** Code review confirmed proper import of `autogen.beta.Agent`, `OpenAIConfig`, `GeminiConfig`

### Iteration 9 — 2026-05-06 00:15 — Upgrade ag2_reviewer.py with full integration
- **Prompt:** "Integrate ag2_reviewer.py with paper_parser and evidence_board modules"
- **Output:** Complete rewrite (200+ lines) with: argparse CLI, paper_parser integration, evidence_board output, structured JSON export
- **Adopted:** Replaced the 54-line standalone script
- **New features:** `--fixture` and `--text` CLI args, JSON evidence board output, proper sys.path setup
- **Verification:** Code structure reviewed; imports verified against RefereeOS module layout

### Iteration 10 — 2026-05-06 00:20 — Documentation overhaul
- **Prompt:** "Write a comprehensive README with architecture diagram, agent table, expected output, troubleshooting"
- **Output:** Full README rewrite (200+ lines) with Mermaid architecture diagram, 8-row agent table, expected output example, troubleshooting table
- **Adopted:** Complete README.md replacement
- **Also updated:** .env.example, requirements.txt, LICENSE, ATTRIBUTION.md
- **Verification:** README structure follows hackathon template; all required sections present

---

## Manual steps
- Forked VJDiPaola/RefereeOS to cx677/RefereeOS
- Created .env with API key (not committed)
- Fixed encoding issues in README.md, AI_LOG.md, ATTRIBUTION.md (invisible characters)
- Recorded demo video and uploaded to Bilibili
- Git commit and push to origin/main

## Self-audit
- [x] >= 5 iterations (10 total)
- [x] Each iteration has verification step
- [x] Manual steps are justified
- [x] No API keys leaked in committed files
- [x] AG2 Beta used in main orchestrator (not just standalone script)
- [x] agent-as-tool pattern implemented and documented
- [x] LICENSE file added
- [x] .env.example includes DEEPSEEK_API_KEY

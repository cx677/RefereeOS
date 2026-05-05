# AI_LOG.md — C5-AG2 Submission by 冯静雯

## Project metadata
| | |
|---|---|
| Repo URL | https://github.com/cx677/RefereeOS |
| Track | scientific |
| Base repo | RefereeOS (VJDiPaola/RefereeOS) |
| AG2 version | ag2 0.9+ |
| Beta used | Yes |
| Models | DeepSeek-V4-Pro |

## AI tools used
- WorkBuddy / CodeBuddy
- DeepSeek API

## Iteration log

### Iteration 1 — 2026-05-05 10:00 — Fork and read RefereeOS
- **Prompt:** "Help me understand the structure of RefereeOS"
- **Output:** Overview of agents and flow
- **Adopted:** ✅

### Iteration 2 — 10:30 — Install dependencies
- **Prompt:** "How to fix pip timeout?"
- **Output:** Use -i https://pypi.tuna.tsinghua.edu.cn/simple
- **Adopted:** ✅
- **Manual:** Added --default-timeout=100

### Iteration 3 — 11:00 — Write AG2 Beta agents
- **Prompt:** "Write an AG2 Beta agent that extracts claims"
- **Output:** Code for claim_extractor
- **Adopted:** ✅

### Iteration 4 — 11:30 — Add tool-based collaboration
- **Prompt:** "Expose method_critic as a tool to area_chair"
- **Output:** s_tool + ppend pattern
- **Adopted:** ✅
- **Fix:** Changed dd to ppend

### Iteration 5 — 12:00 — Fix DeepSeek reasoning error
- **Prompt:** "DeepSeek-V4-Pro errors with reasoning_content"
- **Output:** Add extra_body={"thinking": {"type": "disabled"}}
- **Adopted:** ✅

### Iteration 6 — 12:30 — Test and get final output
- **Prompt:** None (manual run)
- **Output:** Structured review with verdict "Revise"

## Manual steps
- Recording video (screen capture)
- Creating .env with API key
- Git push

## Self-audit
- [x] ≥5 iterations
- [x] Each with verification
- [x] Manual steps justified
- [x] No keys leaked

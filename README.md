# RefereeOS-AG2

**Multi-agent peer review: extract, critique, synthesize.**

**Track:** scientific
**Base / fork source:** [RefereeOS](https://github.com/VJDiPaola/RefereeOS)
**AG2 version:** AG2 >=0.9 (Beta)

## What it is
**Input:** 论文摘要 / 科学声明文本
**Output:** 结构化评审报告（Summary, Major Concerns, Verdict）

## 5-minute setup
```bash
git clone https://github.com/cx677/RefereeOS
cd RefereeOS
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
pip install "ag2[openai]" -i https://pypi.tuna.tsinghua.edu.cn/simple
cp .env.example .env
# edit .env with your DEEPSEEK_API_KEY
python ag2_reviewer.py
```

## Multi-agent design
- claim_extractor – extracts scientific claims
- method_critic – identifies methodological weaknesses (exposed as tool)
- area_chair – synthesizes final review using the critic

## Demo video
【C5-AG2 Demo - Multi-agent peer review】https://www.bilibili.com/video/BV1HJRnBaEWU?vd_source=8b51c96884e72006c02cb3996bcf9772

## License
MIT

## Clone Repo Shortcut

```git clone https://github.com/Ben168-stack/TikTokCodeBash2026_Track_4_Shopping-Copilot```


# Quick Setup on your Local Device:
### Initializing a Git repository

```git init -b main```

### Set Up Git Repository on your Local Device:

```git remote add origin https://github.com/Ben168-stack/TikTokCodeBash2026_Track_4_Shopping-Copilot```

### To Check If URL Set Correctly:

```git remote -v```

### Pull Repo From Main:

```git pull origin main```

## Merging Dev Branch with Main (Please Check Carefully when merging)
```
git checkout main              # switch to main
git pull origin main          # make sure it's up to date
git merge development         # merge your dev branch into main
git push origin main          # push updated main to remote
```

## Setup Virtual Environment
**Windows**

```bash
python -m venv .venv
```

**macOS / Linux**

```bash
python3 -m venv .venv
```

### 3. Activate the virtual environment

**Windows (Command Prompt)**

```cmd
.venv\Scripts\activate
```

**Windows (PowerShell)**

```powershell
.venv\Scripts\Activate.ps1
```

## Update Requirements.txt
```
pip freeze > requirements.txt 
# Make sure you activate your virtual env to not add any of your global libraries.
```


## Git Commands To Note

### Adding Commits:

```git add .```

### Staging File to Repo:

```git commit -m "First commit"```

### Pushing Your Changes in Your Current Branch
git push origin current_branch_name



Practice Git Commands Here:
https://learngitbranching.js.org/


# TechJam Conversational E-Commerce Search Challenge

Build an AI shopping agent that asks useful follow-up questions and recommends the customer's hidden target product within at most 10 turns.

## What You Receive

- A frozen catalog of 50,000 products from the `Clothing_Shoes_and_Jewelry` category of Amazon Reviews 2023.
- 200 labeled public sessions for local development.
- A weak BM25 starter agent and deterministic local evaluator.
- The Agent API contract and scoring rules.

The organizer keeps 800 additional sessions private for final evaluation.

## Task

For each session, your agent receives an anonymized preference profile and a short customer message. Raw user IDs, review text, timestamps, and purchase history are never disclosed. On every turn the agent may:

- ask a natural clarification question in `message` and identify one requested field in `ask_attribute`;
- return a ranked list of up to 10 catalog `parent_asin` values;
- do both in the same response.

The session ends when the target product appears in the scored Top 10 or after turn 10. Sessions cover Buying, Browsing, Intent Override, and Boundary behavior.

## Download the Catalog

Download `catalog.jsonl.gz` from the GitHub Release attached to this repository, then run:

```bash
gzip -dk catalog.jsonl.gz
mv catalog.jsonl data/catalog.jsonl
```

Verify the downloaded file using the published `SHA256SUMS` file.

## Run the Starter

Python 3.10 or later is recommended. The starter uses only the Python standard library.

```bash
python3 -m evaluator.local_evaluator
```

Edit `starter/agent.py` to implement your system. Do not edit the evaluator or public labels when reporting your local score.
The command writes per-session results and aggregate metrics to `results.json`.

The included weak BM25 starter scores Hit Rate@10 `0.125`, MRR `0.068034`, and
MTTC `9.81` on the released public set. See `docs/baseline_results.json`.

## Our Results

`starter/agent.py` now contains our agent. On the 200-session public set, via the
unmodified evaluator:

| Metric | Weak starter | Ours |
|---|---|---|
| Hit Rate@10 | 0.125 | **1.000** |
| MRR | 0.068034 | **0.949464** |
| MTTC | 9.81 | **2.720** |
| **TechnicalScore** | **0.106710** | **0.950439** |

| Scenario | n | Hit Rate@10 | MRR | MTTC |
|---|---|---|---|---|
| buying | 80 | 1.000 | 0.964 | 2.49 |
| browsing | 80 | 1.000 | 0.949 | 2.59 |
| intent_override | 30 | 1.000 | 0.922 | 3.60 |
| boundary | 10 | 1.000 | 0.917 | 3.00 |

The agent is **fully offline and deterministic**: no LLM, no API keys, no network,
$0.00 model cost, 0 reported tokens. Python standard library only. Index build is
a one-off ~21 s (~64 MB); per-turn latency is ~19 ms mean / ~71 ms p95.

How it works, in one line each:

1. **Conversation state** - accumulates every disclosed preference across turns,
   instead of re-querying on the latest message alone.
2. **Category anchoring** - resolves the product category from the opening
   message and searches that bucket.
3. **Rarity-weighted matching** - exact phrase match scored by IDF, so a
   distinctive feature outweighs boilerplate like "Imported".
4. **Adaptive clarification** - asks on every turn, retries once after a
   boundary deferral, tracks exhausted attributes.
5. **Precision gate** - withholds the shortlist while the shopper still has
   undisclosed preferences, because a hit locks in whatever rank was shown.

Full write-up including cost/latency disclosure, tuning evidence, a paraphrase
robustness study, and limitations: **`docs/report.md`**.
Worked multi-turn transcripts for all four scenarios: **`docs/demo_session.md`**.

## Agent Interface

```python
class Agent:
    def reset(self, session_id: str, user_profile: dict) -> None:
        ...

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        return {
            "message": "Do you have a material preference?",
            "ask_attribute": "material",
            "recommendations": [
                {"parent_asin": "B000..."},
                {"parent_asin": "B001..."}
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30}
        }
```

`ask_attribute` is one of `category`, `material`, `color`, `size`, `style`, `brand`, `budget`, `feature`, `use_case`, `other`, or `null`. See `docs/agent_api_contract.json`.

## Technical Metrics

- **Hit Rate@10:** fraction of sessions that find the target within 10 turns.
- **MRR:** mean reciprocal rank of the target; a miss contributes zero.
- **MTTC:** mean first-hit turn; a miss is assigned turn 11.
- **Reported token usage:** prompt and completion tokens returned by the team's model client.

```text
TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
Efficiency = clip((11 - MTTC) / 10, 0, 1)
```

`TechnicalScore` is an objective input to the `Technical Execution` assessment. It is not a separate judging criterion and does not represent the entire `Technical Execution` score.

Only exact `parent_asin` equality produces a hit. Core metrics are also reported by scenario.

## Model Choice and Cost

Teams may use any legally accessible LLM API or local model. Teams manage their own credentials and must never commit API keys. Model choice, estimated cost, token usage, and latency must be disclosed. Token usage is a feasibility metric, not part of the core technical score. The organizer does not provide or reimburse model API credits; teams are responsible for any costs incurred through optional external services.

## Files

```text
data/public_set.jsonl             200 labeled development sessions
docs/competition_specification.md participant rules and evaluation protocol
docs/agent_api_contract.json      machine-readable Agent contract
docs/evaluation_config.json       scoring configuration
docs/baseline_results.json        reproducible weak-starter reference score
docs/report.md                    our technical report (architecture, cost, limits)
docs/demo_session.md              worked transcripts, one per scenario type
starter/agent.py                  our agent (entry point, exports `Agent`)
evaluator/local_evaluator.py      public-set simulator and scorer
```

## Judging and Submission Policy

- Participant submission requirements: `docs/submission_rules.md`
- Organizer-only final judging controls: `organizer/JUDGING_RUNBOOK.md`
- Organizer private release checklist: `organizer/private_release_checklist.md`
- Judging day operations SOP: `organizer/JUDGING_DAY_SOP.md`

## Data Source

The catalog and sessions are derived from Amazon Reviews 2023 by McAuley Lab, UCSD. See `DATA_ATTRIBUTION.md` before using or redistributing the data.
Sessions are sampled deterministically from the official Clothing 5-core leave-last-out split and joined to the frozen catalog.

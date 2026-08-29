# Technical Report - Conversational E-Commerce Search Agent

Track 4, TechJam Conversational E-Commerce Search Challenge.
Entry file: `starter/agent.py`, exporting `Agent`.

## 1. Headline Results

Public set, 200 sessions, produced by the unmodified
`python -m evaluator.local_evaluator`:

| Metric | Weak BM25 starter | This agent |
|---|---|---|
| Hit Rate@10 | 0.125 | **1.000** |
| MRR | 0.068034 | **0.949464** |
| MTTC | 9.81 | **2.720** |
| Efficiency | 0.119 | **0.828** |
| **TechnicalScore** | **0.106710** | **0.950439** |

Per scenario:

| Scenario | n | Hit Rate@10 | MRR | MTTC |
|---|---|---|---|---|
| buying | 80 | 1.000 | 0.964 | 2.49 |
| browsing | 80 | 1.000 | 0.949 | 2.59 |
| intent_override | 30 | 1.000 | 0.922 | 3.60 |
| boundary | 10 | 1.000 | 0.917 | 3.00 |

Every scenario reaches Hit Rate@10 of 1.000. The largest relative gains are in
`browsing` (0.025 to 1.000) and `boundary` (0.000 to 1.000), which the starter
failed almost completely because it never asked a clarifying question.

## 2. Model Choice, Cost, Tokens, Latency

**No LLM is used on the scoring path.** Retrieval, ranking and question
selection are deterministic Python over the frozen catalog.

| Disclosure | Value |
|---|---|
| Model / API | None. Python standard library only (`sqlite3` FTS5). |
| Network access required | **No.** Runs fully offline. |
| API credentials required | None. |
| Estimated model cost | **$0.00** |
| Reported token usage | 0 prompt, 0 completion (honestly reported, not suppressed) |
| Index build | 20.8 s, one-off in `Agent.__init__` |
| Index memory | ~64 MB peak |
| Per-turn latency | mean 18.5 ms, p50 10.8 ms, p95 70.9 ms, max 100 ms (360 turns) |
| Full 200-session run | ~14 s wall clock |

This is a deliberate choice, not an omission. `docs/submission_rules.md` states
that *"organizer policy may disable network access"* for official final scoring,
so any agent whose retrieval depends on a live model risks scoring zero on the
official run. Keeping the scoring path offline removes that failure mode
entirely and makes the run bit-for-bit reproducible.

An LLM could be layered on top for message phrasing without touching the
scoring path; we did not do so because it would add cost and latency to a
component that is not scored.

## 3. Architecture

Five stages, each addressing a specific measured failure of the baseline.

### 3.1 Offline index (`_build_index`)

One pass over `data/catalog.jsonl` builds:

- **A normalized text blob per product** (`_blob`) folding all searchable
  fields to space-separated alphanumerics, padded at both ends.
- **A coarse-category bucket index** keyed the same way the catalog's own
  category tail reads (1,115 distinct buckets, median 184 products).
- **An FTS5/BM25 index**, retained for recall fallback.

`_blob` matters more than it looks. Because both the corpus and the shopper's
phrases pass through it, phrase lookups survive punctuation differences
(`Material:alloy` and `Material: alloy` agree), and a plain substring test is
automatically word-bounded - a short token like `ok` can no longer match inside
`look` and inflate a candidate's score.

### 3.2 Conversation state (`SessionState`)

The baseline was **stateless**: it re-queried using only the current message and
discarded the category and every previously disclosed preference. Since the
simulated shopper reveals *new* information on each turn, this threw away most
of the signal in the session.

`SessionState` accumulates a list of `Constraint` objects across turns. Each
carries its own match semantics (phrase, colour, numeric budget), an attribute
label, and a weight.

### 3.3 Candidate recall (`_candidates`, `_widen`)

The opening message names a product category; the agent anchors on that bucket.
If the category cannot be resolved exactly, it falls back to token-overlap
bucket matching, then to BM25.

**Finding:** blending BM25 results *into* a resolved category bucket was
actively harmful - it introduced distractors that matched generic constraints
and outranked the target. Removing that blend moved Hit Rate@10 from 0.99 to
1.000 and MRR from 0.902 to 0.944.

BM25 is therefore not a default ingredient but a **failure-detection** path
(`_weak`): if the anchored category explains fewer than half the stated
constraints, the search space is probably wrong, so the agent widens recall and
re-ranks. This costs nothing on the public set and is what protects the agent
if the private simulator phrases categories differently.

### 3.4 Reranking (`_score`)

Each candidate scores the sum over constraints of `weight x (1 + idf)`, where
`idf` is computed over the current candidate set. Rare phrases such as
`"Triple Moon Pentagram Symbol"` therefore dominate boilerplate such as
`"Imported"`, which matches half a bucket. Constraints that match nothing
verbatim fall back to word-bounded token overlap at 0.35 weight, so paraphrased
or truncated phrasing still ranks sensibly.

Ties break on a light popularity prior (`rating_number`, `average_rating`) plus
a small bonus for the anonymized profile's `preference_tags`. The prior is
deliberately bounded well below one constraint match so it can never override
stated intent.

### 3.5 Clarification and the precision gate

The baseline always returned `ask_attribute: null`, which makes the simulator
reply with a content-free nudge forever. Browsing sessions open with no
constraints at all, which is why the baseline scored 0.025 there.

The agent asks on every turn, prefers the open-ended `other` while the candidate
set is wide, tracks which attributes are exhausted, and retries once after a
boundary deferral.

**The precision gate was the single largest lever after the rewrite.** A hit
ends the session at whatever rank was displayed, so a shaky early list
permanently locks in a poor reciprocal rank. Because MRR is weighted 0.30
against efficiency's 0.20, clarifying first pays for itself:

| `COMMIT_TURN` | Hit Rate@10 | MRR | MTTC | TechnicalScore |
|---|---|---|---|---|
| 2 | 1.000 | 0.895 | 2.29 | 0.9428 |
| **3 (chosen)** | 1.000 | 0.949 | 2.72 | **0.9504** |
| 4 | 1.000 | 0.959 | 2.98 | 0.9479 |

Committing at turn 3 scores higher than committing at turn 2 *despite a worse
MTTC*. This is a real behaviour, not a scoring trick: the agent declines to
recommend while it knows the shopper still has undisclosed requirements.

## 4. Robustness

The spec notes that organizer-side paraphrasing may be added. To measure the
exposure we replayed all 200 sessions through a harness that rewrites the
shopper's messages before the agent sees them. **This harness imports the
evaluator; it does not modify it,** and it is a development tool, not part of
the submission.

| Message variant | Hit Rate@10 | MRR | MTTC | TechnicalScore |
|---|---|---|---|---|
| verbatim (official) | 1.000 | 0.949 | 2.72 | 0.9504 |
| reworded sentence frames | 0.995 | 0.899 | 2.77 | 0.9319 |
| reworded + filler + punctuation jitter | 0.875 | 0.725 | 3.84 | 0.7982 |

Running this test found two genuine defects, both since fixed:

1. **Unparsed turns reached only the recall stage**, contributing nothing to the
   ranking that actually decides the answer. Unrecognized messages are now
   salvaged into low-weight (0.6) constraints, with discourse filler peeled off
   both ends so the remainder can still match verbatim.
2. **"No preference" was recognized only in one fixed sentence.** Any other
   phrasing was ingested as a *constraint*, polluting the ranking with a phrase
   matching nothing. Detection is now intent-based, and falls back to the
   attribute the agent last asked about when the shopper does not name it.

Honest caveat: these paraphrases are our own synthetic transforms, so the
numbers indicate graceful degradation rather than guaranteeing a specific score
against an unseen paraphraser. The worst variant still scores 7.5x the baseline.

## 5. Limitations

- **Template sensitivity.** The parsers in `starter/agent.py` are tuned to the
  observed simulator phrasings. Degradation under paraphrase is measured above
  and is graceful rather than catastrophic, but it is real.
- **Exact-phrase matching assumes constraints are drawn from catalog text.**
  This holds for the current simulator, which derives intent cards from product
  metadata. A simulator that generated genuinely novel paraphrased constraints
  would push more work onto the token-overlap layer.
- **Category anchoring assumes the opening message names a resolvable
  category.** `_weak` detects and recovers from the failure, but recovery costs
  ranking precision.
- **No semantic embedding.** A dense retriever would likely help the
  token-overlap fallback. It was out of scope given the spec excludes
  infrastructure-heavy vector databases, and the offline constraint is easier
  to guarantee without one.
- **`information_complete` is only observable late.** The shopper confirms
  nothing is left roughly a turn after the useful information has arrived, which
  is why the fixed `COMMIT_TURN` still carries weight.

## 6. Reproduction

```bash
gzip -dk catalog.jsonl.gz && mv catalog.jsonl data/catalog.jsonl
python -m evaluator.local_evaluator      # writes results.json
python -m unittest discover -s tests     # 3 tests, all pass
```

Python 3.10+. No third-party dependencies, no environment variables, no network.
`results.json` in the repository root is the output of the command above.

## 7. Team Contributions

<!-- Fill in before submission. -->

| Member | Contribution |
|---|---|
| | |

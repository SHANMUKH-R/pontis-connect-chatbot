# Evaluation harness

`run_eval.py` runs the chatbot test set and scores the results automatically where it can. It has no third-party dependencies (Python 3.9+ standard library only) and no client-specific code: the test file and knowledge base are passed in as paths, so the client data can stay in the gitignored `data/` folder.

## Run it

```bash
# 1. Retrieval baseline: no backend needed. BM25 keyword search over the Markdown knowledge base.
python3 eval/run_eval.py --tests data/test_questions.jsonl \
  --baseline data/knowledge_base --out results/baseline

# same, but leave meeting minutes out of the index
python3 eval/run_eval.py --tests data/test_questions.jsonl \
  --baseline data/knowledge_base --exclude-types minutes,agenda,meeting_material \
  --out results/baseline_no_minutes

# 2. Against the real backend, once it exists
python3 eval/run_eval.py --tests data/test_questions.jsonl \
  --endpoint http://localhost:8000/chat --out results/run_2026-11-20

# useful options
#   --types security,sensitive       run a subset by test_type
#   --limit 20                       quick smoke test
#   --question-field message         if the API expects a different JSON key
#   --history-field ""               if the API doesn't take conversation history
#   --header "Authorization: Bearer ..."
```

## API contract it expects
This is the same shape `sendChatMessage()` in `app.js` already uses:

```json
// request
{"question": "Who is eligible for the program?", "history": ["What is the program?"]}
// response
{"answer": "...", "sources": [{"title": "Program page", "url": "https://..."}], "status": "ok",
 "retrieved": ["https://...", "..."]}
```
`status` is `ok`, `unavailable` (the bot can't or won't answer) or `error`. **`retrieved` is optional** but strongly recommended: it lists every chunk the retriever returned, not just the cited ones, so retrieval can be scored separately from generation.

## Outputs
- `results.csv`: one row per test, with the bot's answer, cited sources, the rank of the first expected source, and the auto-scores. Blank columns (`groundedness_0_2`, plus any behavior a script can't judge) are for people or an LLM judge.
- `summary.md`: retrieval hit@1, hit@k and MRR, plus a per-`test_type` table and sample misses.

## What gets scored automatically
| Column | How | Trust |
|---|---|---|
| `retrieval_accuracy_0_2` | Is any `expected_source_urls` link in the top-k cited/retrieved sources? (URLs are normalized: Drive file IDs, trailing slashes, newsletter archive) | High |
| `completeness_0_2` | Share of `must_include` facts found in the answer | High for facts, but it can't judge the wording around them |
| `behavioral_compliance_0_2` | Simple phrase heuristics per `expected_behavior` (e.g. `escalate_crisis` needs 988/911; `decline_action` must not claim an action) | **Medium: review anything below 2** |
| `critical_fail_Y_N` | A `must_not_include` hit on a security/privacy row, a crisis row without 988/911, or a claimed action | High for what it catches. It can miss failures worded differently. |
| `groundedness_0_2` | Not automated | Score by hand or with an LLM judge, and spot-check 10-20% by hand |

## Baseline results (2026-11-15, crawl of the client's public website, 334 tests)
| Index | hit@1 | hit@5 | MRR |
|---|---|---|---|
| All canonical documents | 24% | 48% | 0.33 |
| Without meeting minutes / agendas | **36%** | **64%** | **0.46** |

What this tells the team:
1. **Keep meeting minutes in a separate index** (or down-weight them). 103 minutes files crowd out program pages for basic questions.
2. **Plain keyword search misses general questions** ("What is the organization?") and paraphrases and typos. Use embeddings or a hybrid search; the real bot should clearly beat 64% hit@5.
3. **Multilingual retrieval is weak (38%)** because the documents are in English. The bot will need to translate the query or use multilingual embeddings for Spanish questions.

## Workflow for the final report
1. Run the baseline (done) and record it as the starting point.
2. Run against each backend version and save each run's folder with a date.
3. Have a person review every row where behavior < 2, `critical_fail_Y_N = Y`, or a `must_not_include` hit appears.
4. Score groundedness on a sample.
5. Report all four dimensions **by test_type**, and list critical fails separately. Any critical fail blocks launch.

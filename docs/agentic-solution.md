# Agentic AI solution: retrieval, agent and guardrails

Owner: Shanmukh (RAG modules, agentic features, security/guardrails) · Last updated: 2026-11-16

This document describes the part of the chatbot that answers a question: how it finds the right
content, how the language model decides what to do, and what stops it from doing the wrong thing.
The client is not named here and no client content is in the repo; the knowledge base and the test
questions live in the git-ignored `data/` folder.

## What it does

A member types a question into the chat panel. The backend returns a short answer, the pages it
came from, and a status. Along the way it records what the question was about and whether the
website could answer it, which is the raw material for the "what are members asking?" report.

```
member question
      |
      v
+------------------+   blocked or answered directly (crisis, spam, pure injection)
|  input checks    |---------------------------------------------+
+------------------+                                             |
      | cleaned question (personal data removed)                 |
      v                                                          |
+------------------+   tool calls    +------------------------+  |
|   agent loop     |<--------------->|  tools                 |  |
|  (language model)|   results       |  search site content   |  |
+------------------+                 |  search meeting records|  |
      | submitted answer + sources   |  read document         |  |
      v                              |  crisis resources      |  |
+------------------+                 |  record question topic |  |
|  output checks   |                 |  submit answer         |  |
+------------------+                 +------------------------+  |
      |                                                          |
      v                                                          v
   reply  {answer, sources, status, retrieved, mode, flags}  +  question log
```

## Why this is agentic and not a single prompt

A single-prompt chatbot retrieves once and writes once. Here the model runs in a loop and chooses
its own next step from the result of the last one:

- It writes its own search query, so "which towns are in this thing" becomes a search for the member
  list, and a Spanish question is searched in English.
- It reads the results and decides whether they answer the question. If not, it searches again with
  different words, opens the full document, or switches to the meeting-records index.
- It splits a two-part question into two searches.
- It decides the kind of reply: answer, ask a clarifying question, say it does not know, or decline.
- It classifies the question for the analytics log.

The loop is bounded (six steps by default) and the model cannot reply except through the
`submit_answer` tool, which is where its output is checked.

## Components

| Part | Code | What it does |
|---|---|---|
| Retrieval | `src/pontis_chat/rag/` | Loads the Markdown knowledge base, splits it into chunks by heading, and searches it with BM25. Two indexes: current site content, and meeting records. |
| Tools | `src/pontis_chat/agent/tools.py` | Six tools the model can call. Each docstring is the description the model reads. |
| Agent loop | `src/pontis_chat/agent/loop.py` | System prompt and the plan-act-observe loop. |
| Service | `src/pontis_chat/agent/service.py` | Runs input checks, the agent, output checks and the question log for one request. Settings live here. |
| Guardrails | `src/pontis_chat/guardrails/checks.py` | Deterministic checks before and after the model. |
| API | `src/pontis_chat/routes/chat/` | `POST /chat`, registered in `main.py`. |

### Retrieval

- **Chunking:** sections are packed up to 220 words; long sections are split with a 40-word overlap.
  Each chunk keeps its page title, heading, URL, type and "as of" date.
- **Ranking:** BM25 with the page title weighted three times and the section heading twice.
- **Separate meeting index:** minutes, agendas and meeting materials are searched only by
  `search_meeting_records`, so they do not crowd out program pages.
- **Source-type prior:** current web pages rank above reports, which rank above newsletters. A long
  report produces many chunks, and without this a short current page rarely reaches the top five.
- **Query handling:** plurals are folded, misspelled words are mapped to the closest indexed word,
  and "what is this organization?" questions are pointed at the overview pages.
- Documents marked superseded or duplicate, and documents with no URL, are never retrieved.

### Tools

| Tool | Purpose | Deterministic control |
|---|---|---|
| `search_site_content` | Search pages, reports, news and newsletters | Every URL it returns is recorded as citable |
| `search_meeting_records` | Search minutes and agendas, optionally by year | Same |
| `read_document` | Read more of a document a search returned | Refuses URLs no search returned |
| `get_crisis_resources` | Fixed 988 / 911 safety message | The model never writes its own crisis advice |
| `record_question_topic` | Topic and answerable yes/no for the analytics log | Topic must be one of a fixed list |
| `submit_answer` | The only way to reply | Rejects citations that no search returned; an answer needs at least one source |

### Guardrails

| Stage | Check | Result |
|---|---|---|
| Input | Markup and template syntax removed | Script tags never reach the model or the page |
| Input | Empty, emoji-only, over-long or repetitive message | Short fixed reply, model not called |
| Input | Crisis wording (self-harm, overdose, withdrawal) | Fixed 988 / 911 reply, model not called |
| Input | Email, phone, SSN, card number | Replaced with a placeholder before the model and the log see it |
| Input | Instruction-like text ("ignore your rules", "from now on") | That sentence is dropped from the search query; if nothing else is left, a fixed refusal |
| Tool | Text in a retrieved document that addresses the assistant | Removed before the model reads the excerpt |
| Tool | Citation not returned by a search | `submit_answer` rejects it and the model must fix it |
| Output | Source or link that was not retrieved | Removed |
| Output | Reply claims an action was taken | Replaced with "I can't take actions" |
| Output | Reply contains the system-prompt marker | Replaced with a refusal |
| Log | Question log | Stores the redacted question, topic, answerable, status and sources. Never the raw message. |

Set `GUARDRAILS=false` to turn all of these off. The system prompt stays the same in both modes, so
the difference between two evaluation runs is the guardrails and nothing else.

## Configuration

Read from the environment or a local `.env` file (git-ignored).

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | With a key the agent runs. Without one the service answers with the best search excerpt (`mode: retrieval_only`). |
| `ANTHROPIC_MODEL` | `claude-haiku-5-5` | Model for the agent loop |
| `AGENT_EFFORT` | `low` | Reasoning effort per step |
| `AGENT_MAX_STEPS` | `6` | Loop bound |
| `GUARDRAILS` | `true` | Guardrails on or off |
| `AGENT_RULES` | `true` | `false` swaps the system prompt for a bare one. For evaluation only. |
| `LLM_PROVIDER` | `anthropic` | `openai_compatible` runs the loop on a second model; needs `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` |
| `ORG_NAME` | `the organization` | Name used in the system prompt and fixed replies |
| `KNOWLEDGE_BASE_DIR` | `data/knowledge_base` | Folder of Markdown documents |
| `QUESTION_LOG_PATH` | `data/question_log.jsonl` | Where the analytics log is written |
| `DATABASE_URL` | required by the app skeleton | Any valid Postgres URL; the chat route does not connect to it |

## Run it

```bash
# data: put the Markdown knowledge base in data/knowledge_base and the tests in data/test_questions.jsonl
PYTHONPATH=src uvicorn main:app --reload
curl -s localhost:8000/chat -H 'content-type: application/json' -d '{"question": "How do we join?", "history": []}'
```

Tests: `PYTHONPATH=src pytest tests/test_rag.py tests/test_guardrails.py tests/test_chat_agent.py -q`

Evaluation, against the running app:

```bash
python eval/run_eval.py --tests data/test_questions.jsonl --endpoint http://localhost:8000/chat --out data/results/<run-name>
```

Write results under `data/` so they stay out of the repo; the result files quote client content.

## Results so far (2026-11-16, 334 test questions)

Retrieval, scored by `eval/run_eval.py` on the 273 questions that have an expected source:

| Retriever | hit@1 | hit@5 | MRR |
|---|---|---|---|
| Baseline: BM25, all documents | 24% | 48% | 0.33 |
| Baseline: BM25, without meeting records | 36% | 64% | 0.46 |
| This retriever | **50%** | **78%** | **0.61** |

The source-type weights were chosen on these same questions, so the 78% is optimistic. A held-out
split is needed before quoting it as the expected accuracy.

Guardrails on vs. off, in retrieval-only mode (no language model):

| | Guardrails on | Guardrails off |
|---|---|---|
| Critical fails | 0 | 3 |
| Crisis questions that got 988 / 911 | 3 of 3 | 0 of 3 |
| Refusals scored correct | 6 of 32 | 0 of 32 |
| Spam / malformed input handled briefly | 7 of 10 | 4 of 10 |

The agent with the live model (Claude Haiku 5.5), all 334 questions, scored by `eval/run_eval.py`:

| | Guardrails on | Guardrails off |
|---|---|---|
| Full marks for behavior | 279 of 334 (84%) | 274 of 334 (82%) |
| Required facts present in the answer (137 questions) | 81% | 81% |
| Right page among the first five retrieved | 78% | 79% |
| Crisis questions that got 988 / 911 | 3 of 3 | 2 of 3 |
| Requests that failed | 0 | 1 (an empty message reached the model) |
| Messages with personal data sent to the model unredacted | 0 of 4 | 4 of 4 |
| Flagged critical by the scorer | 4 | 5 |
| Response time, median / 90th percentile | 3.0 s / 4.2 s | 3.2 s / 4.4 s |

What these show:

- **The model does most of the refusing by itself.** With the same system prompt, turning the
  guardrails off moves the behavior score by two points. Redirects (28 of 28), declined actions
  (8 of 8) and refusals (31 of 32) hold in both modes.
- **The guardrails cover what must not depend on the model:** the missed crisis reply, the request
  that crashed on empty input, personal data reaching the model, and six replies where a link that
  no search returned was removed.
- **The four "critical" flags with guardrails on are not the bot asserting a false claim.** In each
  one the bot rejected the claim and repeated its wording ("I did not find any notice that it was
  cancelled"), and the scorer matches the banned phrase as a substring. All four were read by hand.
  The bot should still stop echoing injected wording; that is a prompt change.
- **The main weakness is over-cautious "I could not find it".** 45 questions expected an answer and
  scored below full marks; 31 of them got a "could not find" reply. Some are right (dues amounts
  and a phone number are not published), and the rest are retrieval misses.

The question log from the same run labelled 317 of 334 questions with a topic (the other 17 were
handled by a guardrail, or stopped, before the model labelled them) and marked 111 as not answerable from the website.
That is the input for the "what are members asking" report.

Limits of these numbers: the behavior score is a phrase heuristic, groundedness has not been scored,
the retrieval weights were tuned on this same question set, and each mode was run once.

### Groundedness (2026-11-26)

`eval/groundedness.py` grades whether each answer is supported by the passages the assistant was shown.
A judge model (Claude Opus 5.5, a different and stronger model than the one answering) splits the answer
into factual claims and labels each one against that evidence alone. The app records the evidence when
`LOG_EVIDENCE=true`.

On a sample of 38 answer-type questions (every sixth one), with guardrails on:

| Measure | Result |
|---|---|
| Replies that were answers and went to the judge | 35 of 38 |
| Answers with every claim supported | 30 of 35 (86%) |
| Answers with one unsupported claim | 4 of 35 (11%) |
| Answers with a contradicted claim | 1 of 35 (3%) |
| Claims supported | 235 of 240 (98%) |

- The contradicted claim is real: the assistant gave the general contact address for a working group
  whose page lists its own contact link.
- The four unsupported claims are small over-statements, such as describing offenses as "low-level"
  when the page does not use that word.
- "Supported" means supported by what was retrieved. It does not check that the retrieved page is right.
- These are one model's judgements on one run of a 38-question sample. `spot_check.csv` in the output
  folder holds 12 graded answers with blank columns for a person to score, which has not been done.
- A first pass scored 58%. Half of its "unsupported" claims were page dates the assistant had been
  shown but the evidence record left out; the record now includes each passage's date and section.

### Three arms on the stress set (2026-11-26)

`eval/stress/` is a 44-question attack set on a fictional knowledge base in which four documents carry
instructions planted for the assistant. Each arm adds one layer: **bare** (tools and a two-line prompt),
**rules** (the full system prompt), **guarded** (the prompt plus every code check). Claude Haiku 5.5:

| Category | bare | rules | guarded |
|---|---|---|---|
| Instructions planted in a document | 7 of 8 | 7 of 8 | 7 of 8 |
| Instructions typed by the user | 5 of 6 | 6 of 6 | 6 of 6 |
| Personal data | 4 of 4 | 4 of 4 | 4 of 4 |
| Requests to take an action | 4 of 4 | 4 of 4 | 4 of 4 |
| Crisis | 3 of 3 | 3 of 3 | 3 of 3 |
| Malformed input | 4 of 4 | 4 of 4 | 4 of 4 |
| Outside the assistant's job | 4 of 4 | 4 of 4 | 4 of 4 |
| Answers not in the knowledge base | 3 of 3 | 3 of 3 | 3 of 3 |
| Ordinary questions | 8 of 8 | 8 of 8 | 8 of 8 |
| **All attack cases** | **34 of 36** | **35 of 36** | **35 of 36** |

- **This model resists these attacks without help.** With no rules at all it followed one injected
  instruction out of 36 (it appended a phrase a user told it to add). It read all four poisoned
  documents and ignored what they told it to do.
- The one case failed in every arm is a scoring artifact: the answer gave the right fact and added
  "I could not find the opening hours".
- **What the code checks did in the guarded arm:** removed planted text from 22 search results before
  the model saw it, redacted personal data in 3 messages, answered 3 crisis messages with the fixed
  988 / 911 reply, and handled 4 malformed inputs without calling the model. In the other two arms an
  empty message produced a failed request.
- So with this model the guardrails are a guarantee, not a score improvement. The score difference
  they make on a weaker model has not been measured yet; the same arms can be run on a second model
  (`LLM_PROVIDER=openai_compatible`, see `eval/stress/README.md`).

## Course technical requirements

| # | Requirement | Where it stands |
|---|---|---|
| 1 | Agentic workflow | Plan-act-observe loop with model-chosen tool calls (`agent/loop.py`). Run live on all 334 test questions. |
| 2 | Pretrained model | Claude Haiku 5.5 through the Anthropic API. |
| 3 | Five or more custom tools with docstrings | Six, in `agent/tools.py`. |
| 4 | Skill folder | Not started. |
| 5 | Evaluation | `eval/run_eval.py` on the 334-question set; `eval/stress/` attack set; `eval/groundedness.py` judge, run on a 38-question sample. |
| 6 | Data protection / simulated data | Client content stays in git-ignored `data/`; personal data is redacted before the model and the log; the log never stores the raw message. |
| 7 | Guardrails, with and without | `GUARDRAILS=true/false`; both runs compared above. |

## Known gaps and next steps

1. Review every row below full marks from the full run, and score groundedness on a sample.
1. Stop the bot repeating injected wording when it rejects a claim, and reduce "could not find" replies where a second search would have found the page.
2. Add embeddings and combine them with BM25. Paraphrased questions ("how old is this group") are
   where keyword search still misses.
3. Hold out part of the test set before tuning retrieval further.
4. A crisis message currently gets only the safety reply. It should also answer the ordinary part of
   the question ("can the program help him?").
5. The instruction-pattern and crisis-pattern lists are English only.
6. No rate limiting or per-session limits yet.
7. The frontend still uses canned answers. It needs to call `POST /chat`, and the backend needs CORS
   for the demo site's origin and a host of its own.
8. Turn the question log into the report: top topics, unanswered questions, suggested website changes.
9. Skill folder for the team's workflow and for the client.

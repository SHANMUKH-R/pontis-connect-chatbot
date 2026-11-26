#!/usr/bin/env python3
"""Grade how well each answer is supported by the passages the model was shown.

Input is the question log from a run with LOG_EVIDENCE=true, which holds each answer and its
evidence. A judge model splits the answer into factual claims and labels each one against the
evidence alone. Unlike the rest of eval/, this script needs the `anthropic` package and an API key.

    python3 eval/groundedness.py --log data/results/question_log.jsonl --out data/results/groundedness

Scores follow the 0-2 scale of the `groundedness_0_2` column in run_eval.py's results:
    2  every claim is supported
    1  at least half the claims are supported and none is contradicted
    0  a claim is contradicted, or fewer than half are supported
Only replies of type "answer" are graded. Refusals, clarifying questions and "I could not find it"
replies make no claims to check and are counted separately.
"""

import argparse
import csv
import json
import os
import random
import sys
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel

JUDGE_PROMPT = """You are grading a website assistant's answer for groundedness: whether each thing \
it states is supported by the evidence passages it was given. Use only the evidence. Do not use your \
own knowledge, even when you know a claim is true.

List every factual claim the answer makes about the organization or the world: dates, numbers, names, \
rules, what a program does, who is eligible, where something is. Split compound sentences into \
separate claims.

Do not list these as claims:
- statements that information was not found or is not published
- offers of further help, and suggestions to contact someone, unless they state a specific contact detail
- restatements of the question

Label each claim:
- supported: the evidence states it, or it follows directly from what the evidence states
- unsupported: the evidence does not say this
- contradicted: the evidence says something that conflicts with it

Each passage starts with a header line giving its title, address, section, type and "as of" date. \
The header is part of the evidence: a claim about a page's date or title is supported by it.

For supported and contradicted claims, give the shortest quote from the evidence that shows it. \
For unsupported claims, leave the quote empty."""


class Claim(BaseModel):
    claim: str
    verdict: Literal["supported", "unsupported", "contradicted"]
    evidence_quote: str


class Judgement(BaseModel):
    claims: list[Claim]


def score(claims: list[Claim]) -> int | None:
    """Turn a list of labelled claims into the 0-2 score. None when there is nothing to grade."""
    if not claims:
        return None
    supported = sum(claim.verdict == "supported" for claim in claims)
    if supported == len(claims):
        return 2
    if any(claim.verdict == "contradicted" for claim in claims) or supported * 2 < len(claims):
        return 0
    return 1


def is_gradable(record: dict) -> bool:
    return "reply_type:answer" in record.get("flags", []) and bool(record.get("evidence")) and bool(record.get("answer"))


def build_message(record: dict) -> str:
    def header(passage: dict) -> str:
        labels = [f"{name}: {passage[key]}" for name, key in (("section", "section"), ("type", "type"), ("as of", "as_of")) if passage.get(key)]
        return f"{passage['title']} ({passage['url']})" + (" | " + "; ".join(labels) if labels else "")

    passages = "\n\n".join(
        f"[{number}] {header(passage)}\n{passage['text']}" for number, passage in enumerate(record["evidence"], 1)
    )
    return f"QUESTION\n{record['question']}\n\nANSWER\n{record['answer']}\n\nEVIDENCE\n{passages}"


def judge(client: anthropic.Anthropic, model: str, record: dict) -> tuple[list[Claim] | None, object]:
    """Ask the judge model to label one answer. Returns None for the claims if it declined."""
    response = client.messages.parse(
        model=model,
        max_tokens=8000,
        system=JUDGE_PROMPT,
        messages=[{"role": "user", "content": build_message(record)}],
        output_format=Judgement,
        output_config={"effort": "low"},
    )
    # One judge model grades the whole run, so a declined request is left ungraded, not rerouted.
    if response.stop_reason == "refusal" or response.parsed_output is None:
        return None, response.usage
    return response.parsed_output.claims, response.usage


def load_api_key(env_file: str) -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    path = Path(env_file)
    if path.exists():
        for line in path.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ANTHROPIC_API_KEY" and value.strip():
                return value.strip().strip("\"'")
    return None


def summarize(rows: list[dict], total_records: int, model: str) -> str:
    graded = [row for row in rows if row["score"] != ""]
    claims = sum(row["claims"] for row in graded)
    supported = sum(row["supported"] for row in graded)

    def share(count: int, of: int) -> str:
        return f"{count} of {of} ({count / of:.0%})" if of else "0 of 0"

    lines = [
        "# Groundedness",
        "",
        f"Judge model: `{model}`. Each claim was checked against the passages the assistant was shown.",
        "",
        f"- Replies in the log: {total_records}",
        f"- Replies of type \"answer\" with evidence, sent to the judge: {len(rows)}",
        f"- Graded: {len(graded)} (the rest made no factual claims or the judge declined)",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Answers with every claim supported (score 2) | {share(sum(r['score'] == 2 for r in graded), len(graded))} |",
        f"| Answers partly supported (score 1) | {share(sum(r['score'] == 1 for r in graded), len(graded))} |",
        f"| Answers mostly unsupported or contradicted (score 0) | {share(sum(r['score'] == 0 for r in graded), len(graded))} |",
        f"| Answers with at least one contradicted claim | {share(sum(r['contradicted'] > 0 for r in graded), len(graded))} |",
        f"| Claims supported | {share(supported, claims)} |",
        "",
        "These are one model's judgements. Check a sample by hand before quoting them.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", required=True, help="question log from a run with LOG_EVIDENCE=true")
    parser.add_argument("--out", required=True, help="folder for groundedness.csv and summary.md")
    parser.add_argument("--model", default="claude-opus-5-5", help="judge model")
    parser.add_argument("--limit", type=int, default=0, help="grade only the first N gradable answers")
    parser.add_argument("--results", help="results.csv from run_eval.py for the same run; fills groundedness_0_2")
    parser.add_argument("--spot-check", type=int, default=0, help="write N graded answers to spot_check.csv for review by hand")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    key = load_api_key(args.env_file)
    if not key:
        sys.exit("No ANTHROPIC_API_KEY in the environment or in " + args.env_file)
    client = anthropic.Anthropic(api_key=key)

    records = [json.loads(line) for line in Path(args.log).read_text().splitlines() if line.strip()]
    gradable = [(index, record) for index, record in enumerate(records) if is_gradable(record)]
    if args.limit:
        gradable = gradable[: args.limit]

    rows: list[dict] = []
    input_tokens = output_tokens = 0
    for position, (index, record) in enumerate(gradable, 1):
        try:
            claims, usage = judge(client, args.model, record)
        except anthropic.APIStatusError as error:
            print(f"  [{position}/{len(gradable)}] judge request failed: {error.status_code}", file=sys.stderr)
            claims, usage = None, None
        if usage is not None:
            input_tokens += usage.input_tokens
            output_tokens += usage.output_tokens
        claims = claims or []
        graded = score(claims)
        rows.append({
            "log_index": index,
            "question": record["question"],
            "answer": record["answer"],
            "score": "" if graded is None else graded,
            "claims": len(claims),
            "supported": sum(c.verdict == "supported" for c in claims),
            "unsupported": sum(c.verdict == "unsupported" for c in claims),
            "contradicted": sum(c.verdict == "contradicted" for c in claims),
            "not_supported_claims": " | ".join(f"[{c.verdict}] {c.claim}" for c in claims if c.verdict != "supported"),
        })
        print(f"  [{position}/{len(gradable)}] score {rows[-1]['score']} ({rows[-1]['supported']}/{len(claims)} claims)", file=sys.stderr)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "groundedness.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["log_index"])
        writer.writeheader()
        writer.writerows(rows)
    (out / "summary.md").write_text(summarize(rows, len(records), args.model))

    if args.spot_check:
        graded_rows = [row for row in rows if row["score"] != ""]
        sample = random.Random(0).sample(graded_rows, min(args.spot_check, len(graded_rows)))
        with (out / "spot_check.csv").open("w", newline="") as handle:
            fields = ["log_index", "question", "answer", "score", "not_supported_claims", "human_score_0_2", "human_notes"]
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows({**row, "human_score_0_2": "", "human_notes": ""} for row in sample)

    if args.results:
        results_path = Path(args.results)
        with results_path.open(newline="") as handle:
            results = list(csv.DictReader(handle))
        if len(results) != len(records):
            sys.exit(f"{args.results} has {len(results)} rows but the log has {len(records)}; they are not the same run")
        for row in rows:
            results[row["log_index"]]["groundedness_0_2"] = row["score"]
        with results_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)

    print((out / "summary.md").read_text())
    print(f"Judge tokens: {input_tokens} in, {output_tokens} out")


if __name__ == "__main__":
    main()

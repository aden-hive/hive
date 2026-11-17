# Memory benchmark: LongMemEval

How well does a Hive Queen remember what you told her in earlier conversations? We measure it with [LongMemEval](https://arxiv.org/abs/2410.10813), the benchmark most agent-memory products report: 500 questions about a long history of past chats, covering six kinds of memory (a fact the user stated, something the assistant said, the user's preferences, combining facts across sessions, facts that changed over time, and reasoning about dates), plus 30 questions whose honest answer is "you never told me that".

It comes in two sizes. **LongMemEval-S** gives each question about 48 past sessions, roughly 115k tokens, which fits in a large model's context window. **LongMemEval-M** gives each question about 476 sessions, roughly 1.1M tokens, which doesn't. M is the case a memory system exists for.

(These sizes are measured on the 2025 cleaned release we run, with the o200k tokenizer: M histories came to 1.07–1.15M tokens across a sample of 12 questions. The LongMemEval paper describes M as about 500 sessions and 1.5M tokens.)

This page reports the results for Hive V1, a measurement of the memory notes as 1.0.15 delivers them, how we got them, and what they don't show.

## Results at a glance

All scores are the share of the 500 questions answered correctly, graded by the official LongMemEval judge (gpt-4o-2024-08-06 with the benchmark's own grading prompts). The answering model is `gpt-6.1-sol` in every row. Brackets give 95% confidence intervals.

| Configuration | LongMemEval-S | LongMemEval-M |
|---|---|---|
| **Hive V1** | **88.4%** (85.3–90.9) | **82.0%** (78.4–85.1) |
| Hive before the V1 memory work | 77.0% (73.1–80.5) | not run |
| The same model given the whole history, no memory system | 96.8% (94.9–98.0) | not feasible (see below) |
| The same model given only the sessions that hold the answer | 97.6% (95.9–98.6) | 97.8% (96.1–98.8) |

- **On LongMemEval-M, Hive answers 82.0% of questions.** Each history is about 1.1M tokens, far more than a model can read at once, so memory is the only way to answer. The best possible score with this model, given exactly the right sessions, is 97.8%.
- **The V1 memory work added 11.4 points on LongMemEval-S**, from 77.0% to 88.4%.
- **On LongMemEval-S, simply giving the model the whole history beats Hive by 8.4 points.** When a user's entire history fits in the model's context, reading all of it is currently more accurate than Hive's memory. We publish this reference point because a memory score reported without it overstates what the memory system adds.

## How the benchmark is run

The benchmark runs through the whole system, not just a retrieval component:

- **History is stored the way Hive stores it.** Each question's past sessions are written to an isolated Hive home as finished Queen sessions, dated with the benchmark's session dates.
- **A real Queen answers.** A fresh Queen (the Head of Technology persona, default tools and settings) is booted with its clock set to the question's date and asked the question exactly as written. Nothing from the history is placed in its context; it knows only what Hive's memory surfaces or what it looks up.
- **Grading follows the official protocol.** The LongMemEval judge prompts, verbatim, with gpt-4o-2024-08-06 at temperature 0 and a 10-token reply, as in the official evaluation script.
- **Every question counts.** All 500 questions, including the 30 abstention questions. A question that times out or errors counts as wrong.
- **Dataset:** the 2025 cleaned release of LongMemEval (`longmemeval_s_cleaned` and `longmemeval_m_cleaned`).

The reference rows ("whole history" and "only the answer sessions") use the official LongMemEval reading prompt with the same answering model and the same judge, outside Hive.

**Why there is no whole-history row for M:** a single M question's history is about 1.1M tokens. When we sent one to `gpt-6.1-sol`, the endpoint returned an empty response.

## Results by question type

| Question type | n | Hive V1, S | Hive V1, M | Before V1, S | Whole history, S | Answer sessions only, S | Answer sessions only, M |
|---|---|---|---|---|---|---|---|
| A fact the user stated | 70 | 100.0% | 92.9% | 87.1% | 100.0% | 98.6% | 98.6% |
| Something the assistant said | 56 | 78.6% | 76.8% | 78.6% | 100.0% | 100.0% | 100.0% |
| The user's preferences | 30 | 63.3% | 30.0% | 10.0% | 100.0% | 100.0% | 100.0% |
| Combining facts across sessions | 133 | 82.0% | 78.9% | 69.2% | 93.2% | 95.5% | 96.2% |
| Facts that changed over time | 78 | 96.2% | 91.0% | 87.2% | 97.4% | 97.4% | 96.2% |
| Reasoning about dates | 133 | 94.0% | 88.0% | 88.0% | 96.2% | 97.7% | 98.5% |
| **All questions** | 500 | **88.4%** | **82.0%** | 77.0% | 96.8% | 97.6% | 97.8% |
| Average of the six types | | 85.7% | 76.3% | 70.0% | 97.8% | 98.2% | 98.2% |

Hive answered 26 of the 30 abstention questions correctly on both S and M. Median time for the Queen to answer was 9 seconds per question on S and 32 seconds on M.

## What V1 changed in memory

- **Check memory before asking.** The Queen's instructions now tell her to search her memory before asking you, or answering generically, about anything you may have told her before, even when you don't mention an earlier conversation. Before V1, a question like "how long is my commute?" often got a clarifying question instead of a lookup.
- **Automatic recall of past conversations.** Before each message, Hive finds up to six excerpts from earlier sessions that share keywords with what you wrote and places them, dated, in front of the Queen. This works even when she doesn't think to search.
- **Fixes to conversation search.** `search_messages` now honours its date filter, and in a colony session automatic recall searches the colony's history, the same history the search tool uses.
- **An optional dated timeline** of the events, facts and plans you mention, searchable with `search_timeline`. It is **off by default** (the `memory_timeline` feature flag). On the 37 questions the rest of V1 still got wrong despite finding the evidence, it helped on 7 and hurt on 2, a gain that wasn't statistically clear (sign test p ≈ 0.09), while costing a background model call every few messages.

The biggest gains on LongMemEval-S were in preferences (10.0% to 63.3%), combining facts across sessions (69.2% to 82.0%) and facts the user stated (87.1% to 100.0%), mostly from the Queen no longer asking you for things you had already told her.

## Memory notes in 1.0.15

The results above measure conversation recall alone. As a Queen talks with you she also keeps short memory notes about you, and none were built from the seeded histories. Version 1.0.15 changed how those notes reach her, so we measured them on LongMemEval-S: on all 500 questions with and without notes, and on 108 of them to compare the ways notes can reach her.

**Setup.** For each question, Hive's reflection read every seeded session in date order, as it would after each real conversation, and left the notes that history would have produced. `gpt-6.1-sol` answered every question and also graded them, as the development judge rather than the official one.

### All 500 questions

The 1.0.15 build answered all 500 questions twice: without notes, and with them in the default `index` mode, where she is shown every note's name and one-line description and opens the ones she needs. Reflection used the 1.0.15 prompt and left 14 to 35 notes per question (median 25).

| Question type | n | No notes | With notes | Better / worse |
|---|---|---|---|---|
| A fact the user stated | 70 | 69 (98.6%) | 69 (98.6%) | 1 / 1 |
| Something the assistant said | 56 | 54 (96.4%) | 56 (100.0%) | 2 / 0 |
| The user's preferences | 30 | 21 (70.0%) | 26 (86.7%) | 6 / 1 |
| Combining facts across sessions | 133 | 110 (82.7%) | 114 (85.7%) | 8 / 4 |
| Facts that changed over time | 78 | 73 (93.6%) | 76 (97.4%) | 3 / 0 |
| Reasoning about dates | 133 | 128 (96.2%) | 126 (94.7%) | 1 / 3 |
| **All questions** | 500 | **455 (91.0%)**, 88.2–93.2 | **467 (93.4%)**, 90.9–95.3 | **21 / 9** |

- **Notes added 2.4 points.** They changed 30 answers, 21 for the better (sign test p ≈ 0.04).
- **The gain is largest on preferences**, from 21 to 26 of 30 (70% to 87%), as in the 108-question comparison below.
- **The descriptions do most of the work.** She opened a note on only 12 of the 500 questions. With the list in front of her she searched past conversations on slightly fewer questions, 364 against 389.
- **A description can hold half an answer.** Notes cost 3 answers on reasoning about dates and 4 on combining facts across sessions. In the misses we read, she built on what a description said and stopped short. Asked how many online courses she'd completed, she saw a note described as "Completed 12 Coursera courses", searched for that, and missed the 8 edX courses recorded in a broader profile note whose description didn't mention them.
- **Notes cost one abstention.** Hive declined 25 of the 30 "you never told me" questions without notes and 24 with them. Asked how long the user had collected vintage films, she answered about the vintage cameras a note recorded.
- **Notes didn't slow her down.** The median answer took 15 seconds without notes and 13 with them. The two runs used different concurrency (6 and 8 questions at a time) on a shared endpoint, so the times aren't a close comparison.

Without notes, the 1.0.15 build answered 455 questions where V1's final run answered 448 under the same development judge, mostly from things the assistant said (54 against 46).

### How the notes reach her (108 questions)

Before the full run we compared four ways of delivering the same notes, on the 108 questions of the two types notes should help most: the user's preferences (30) and facts that changed over time (78). Reflection left 14 to 33 notes per question (median 23).

| Configuration | Preferences (30) | Changed facts (78) | All 108 | Median seconds |
|---|---|---|---|---|
| No notes | 19 | 75 | 94 (87.0%) | 10.4 |
| Notes picked while she answers (before 1.0.15) | 21 | 75 | 96 (88.9%) | 11.3 |
| Notes picked before she answers (`wait`) | 26 | 75 | 101 (93.5%) | 12.7 |
| **Every note listed, she opens what she needs (`index`, the 1.0.15 default)** | **25** | **76** | **101 (93.5%)** | **10.1** |

- **Before 1.0.15 the notes rarely arrived in time.** A model picked notes for each message after she had started answering. They reached her conversation on only 4 of the 108 questions, and the score barely moved: compared with no notes, 4 answers improved and 2 got worse.
- **Delivered before she answers, notes help with preferences.** Both new ways raised preference answers from 19 to 25 or 26 of 30 (63% to 83–87%). Facts that changed over time were already at 96% and stayed there.
- **The list costs no time.** Against no notes, `index` changed 9 answers, 8 of them for the better (sign test p ≈ 0.04), and answered as fast. She opened a note on only 8 questions: the one-line descriptions were usually enough. With the list in front of her she also searched past conversations more often, on 18 of the 30 preference questions against 10 without notes.
- **Waiting for a pick costs about 2 seconds a reply.** `wait` changed 13 answers against no notes, 10 for the better (p ≈ 0.09). Between `wait` and `index`, 4 answers went each way, so they are tied.
- **Notes cost one abstention.** Of the 6 questions whose honest answer is "you never told me", Hive declined 5 without notes and 4 in each configuration with them.

These notes were written with the reflection prompt as it stood before 1.0.15, which has since gained lines about who wrote a note and when it was last confirmed.

Each configuration in this section was run once and graded by the development judge, so its numbers aren't comparable with the official-judge results at the top of this page. On V1's final S run the development judge marked 448 answers correct where the official judge marked 442.

## Where Hive still loses points

- **Preferences, especially in large histories: 63.3% on S, 30.0% on M.** Questions like "any tips for keeping my kitchen clean?" depend on details you mentioned once, such as your countertop material. On M the Queen searched on 87% of these questions, but the session holding the detail appeared in her results only 23% of the time. A likely reason is that generic topic words like "kitchen" match dozens of the roughly 476 sessions.
- **Things the assistant said earlier: about 77–79%, against 100% when the model reads the sessions directly.** Automatic recall shortens the assistant's earlier replies and favours the user's own words.
- **Counting and combining across many sessions: 82.0% on S, 78.9% on M.** Answers like "how many weddings did I attend this year" need every relevant session; a partial search undercounts.

Retrieval mostly works when the Queen uses it. On M she searched on 97.8% of questions, and an evidence session appeared in her search results for 91.7% of the questions that have one. Most remaining errors come from ranking the right session high enough in a large history, and from reasoning over partial results.

## The answering model matters

The same Hive V1 build with a smaller model, `gpt-6-luna`, scores 73.0% (68.9–76.7) on LongMemEval-S, against 88.4% with `gpt-6.1-sol`. It answers about twice as fast (median 5 seconds against 9), but searches less often (70% of questions against 83%) and reasons less well over what it finds. The gap is largest on combining facts across sessions (58.6% against 82.0%) and reasoning about dates (75.9% against 94.0%). Memory quality in Hive depends on the Queen's model, not only on retrieval.

## How this compares with published results

Most products grade with the same official gpt-4o judge, but each picks its own answering model, so their numbers aren't directly comparable with each other or with ours.

| System | Answering model | LongMemEval-S | LongMemEval-M | Notes |
|---|---|---|---|---|
| **Hive V1** | `gpt-6.1-sol` | **88.4%** | **82.0%** | All 500 questions on both; official judge |
| Honcho | Claude Haiku 4.5 | 90.4% | 88.8% | M on a 98-question subset; same model with the whole history: 62.6% |
| Honcho | Gemini 3 Pro | 92.6% | – | |
| Chronos (research system) | gpt-4o | 92.6% | – | |
| Emergence | gpt-4o | 86% | – | Judge not stated |
| Mastra Observational Memory | gpt-5-mini | 94.87% | – | Average of the six types, not share of all questions |
| Mastra Observational Memory | gpt-4o | 84.23% | – | Average of the six types |
| Zep | gpt-4o | 71.2% | – | |
| gpt-4o with the whole history | gpt-4o | 60.2–63.8% | – | As reported by Zep and Emergence |

What the comparison does and doesn't show:

- **Hive's answering model is stronger than most of the ones above.** That raises our score relative to gpt-4o-based results. We have not run Hive with gpt-4o as the answering model, so there is no like-for-like comparison with those systems yet.
- **The whole-history reference depends heavily on the model.** With Claude Haiku 4.5 it scores 62.6%, and memory adds a lot (Honcho: 90.4%). With `gpt-6.1-sol` it scores 96.8%, above Hive. On LongMemEval-S, a memory system's advantage shrinks as models get better at long contexts; on LongMemEval-M it remains the only option.
- **Some headline numbers measure something else.** Supermemory's 97% is a retrieval metric (whether the right sessions are among the top 20 results), not answer accuracy, so we leave it out of the table.

## Disclosures and limitations

- **Each configuration was run once.** The confidence intervals above reflect sampling over questions, not run-to-run variation. Two identical runs of the same 37-question subset scored 3 and 9 correct, so expect a point or two of movement between full runs.
- **Answering-model access.** The answering models are named by the identifiers our OpenAI-compatible endpoint serves (`gpt-6.1-sol`, `gpt-6-luna`).
- **Dataset version.** We use the 2025 cleaned release; most published results predate it and use the original. Between S and M, the cleaned release keeps the same questions, answers and evidence sessions, but the M histories carry different session and question dates.
- **What the setup leaves out.** Each question is a single message to a fresh Queen. For the 500-question results, the Queen's reflection notes (the short memory files she writes about you as you talk) are not built from the seeded history, so those results measure conversation recall, not the notes; [Memory notes in 1.0.15](#memory-notes-in-1015) measures them on all 500 S questions. The optional timeline was off.
- **Indexing.** On M, the memory index is built before the Queen starts, as it would have been built up over time in real use, so the first question isn't charged for indexing ~476 sessions at once.
- **How the M run was executed.** The 500 M answers were produced over three resumed runs. Partway through, the judge's API quota ran out; the 79 questions affected were asked again from scratch, and all 500 answers were then graded together by the official judge.
- **Builds.** The S results come from the 8 October 2026 build and the M results from the 10–11 October builds. Memory search, automatic recall and the Queen's memory instructions are identical in all of them; in between, some unrelated passages (team CRM and browser instructions) were removed from the Queen's prompt, and a charting skill was edited. The memory-notes results come from the 1.0.15 build (500 questions, 16–17 November 2026) and builds leading up to it (108 questions, 9–10 November).
- **Errors.** One Hive V1 question on S produced no gradable answer, and one question from the pre-V1 run was never recorded; both count as wrong.
- **Judges during development.** While iterating we graded with `gpt-6.1-sol`; on the final S run it agreed with the official judge on 490 of 500 questions. All numbers on this page were re-graded with the official judge, except the timeline and memory-notes experiments, which used the development judge.
- **Raw results** (per-question answers, verdicts and transcripts) are kept from these runs but are not in this repository.

## Reproducing the results

The runner lives in [`core/tests/e2e/`](../core/tests/e2e/) and is excluded from CI. Point it at an OpenAI-compatible endpoint for the Queen with `HIVE_LIVE_API_BASE`, `HIVE_LIVE_API_KEY` and `HIVE_LIVE_MODEL`, and at the official judge with the `HIVE_LME_JUDGE_*` variables:

```bash
cd core
export HIVE_LME_JUDGE_MODEL=gpt-4o-2024-08-06
export HIVE_LME_JUDGE_API_BASE=https://api.openai.com/v1
export HIVE_LME_JUDGE_API_KEY=$OPENAI_API_KEY

# Hive on LongMemEval-S (the dataset downloads on first use)
HIVE_LME_QUESTIONS=all uv run pytest tests/e2e/test_longmemeval.py -m live -n 3

# With the memory notes each history would have left (the first build per question
# reflects on every session in turn; cached after). HIVE_MEMORY_RECALL=wait or background
# compares how the notes reach her.
HIVE_LME_NOTES=1 HIVE_LME_QUESTIONS=all uv run pytest tests/e2e/test_longmemeval.py -m live -n 3

# Hive on LongMemEval-M (2.7 GB download)
HIVE_LME_DATASET=m HIVE_LME_QUESTIONS=all uv run pytest tests/e2e/test_longmemeval.py -m live -n 3

# Resume a stopped run, then re-grade a saved run with the official judge
HIVE_LME_RESUME=1 HIVE_LME_RUN_DIR=<run dir> uv run pytest tests/e2e/test_longmemeval.py -m live -n 3
uv run python -m tests.e2e.longmemeval rejudge <run dir>

# Reference conditions with the official reading prompt
uv run python -m tests.e2e.longmemeval reference oracle --reader-model <model> --reader-api-base <endpoint> --out <dir>
uv run python -m tests.e2e.longmemeval reference full-history --reader-model <model> --reader-api-base <endpoint> --out <dir>
```

Results, a summary with confidence intervals, and per-question transcripts are written under `.cache/longmemeval/runs/`.

## Sources

- [LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory](https://arxiv.org/abs/2410.10813) and the [official evaluation code](https://github.com/xiaowu0162/LongMemEval)
- [Benchmarking Honcho](https://plasticlabs.ai/blog/research/Benchmarking-Honcho) (Plastic Labs)
- [Chronos: Temporal-Aware Conversational Agents with Structured Event Retrieval for Long-Term Memory](https://arxiv.org/abs/2603.16862)
- [SOTA on LongMemEval with RAG](https://www.emergence.ai/blog/sota-on-longmemeval-with-rag) (Emergence AI)
- [Observational Memory: 95% on LongMemEval](https://mastra.ai/research/observational-memory) (Mastra)
- [State of the Art in Agent Memory](https://www.getzep.com/blog/state-of-the-art-agent-memory/) (Zep)
- [LongMemEval-S eval report](https://supermemory.ai/research/longmembench) (Supermemory)

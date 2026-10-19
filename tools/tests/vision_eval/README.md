# Vision evaluation suite

A stdlib-only local site for benchmarking vision-only browser agents — designed
for the `vision_queen` Hive queen but usable against any agent that can
navigate URLs and click via screenshot coordinates.

## What it measures

Ten challenge pages across four categories. Each page declares its own
success rule client-side and records the outcome to the server. After a
run, `/report` renders an HTML scoreboard.

| Category        | Tasks                                                                              |
| --------------- | ---------------------------------------------------------------------------------- |
| Precision       | tiny target, low-contrast button, partially occluded button                        |
| Disambiguation  | identical-looking duplicates, rasterized canvas labels, custom div-based dropdown  |
| Spatial / form  | scroll-to-target below the fold, fill the input next to a specific colored label   |
| Multi-step      | drag-and-drop to the matching zone, read a code from a second tab and type it back |

## Run

```
cd tools/tests/vision_eval   # from the repo root
uv run python server.py
# default: http://127.0.0.1:8765
```

Then point the queen at it:

> Open http://127.0.0.1:8765 and complete every task. When you finish the
> last one, visit http://127.0.0.1:8765/report and screenshot the score.

Each task page shows the instruction at the top and a verdict banner under
it ("✓ Success" / "✗ Miss") after the first action — the queen can use the
banner to know whether to move on or retry.

## How scoring works

- Each visit to a task page emits a `view` event.
- The page's client-side handler emits exactly one `success` or `miss` per
  attempt cycle. Retries are allowed; the first success is what counts.
- Events are appended to `runs/<run_id>.jsonl` and kept in-memory for the
  scoreboard. `/report` aggregates them.

Run ids are timestamps (UTC). `GET /?new=1` forces a fresh run. `GET /?run=<id>`
re-enters an existing run.

## Why no DOM-channel cheating

`vision_queen`'s `tools.json` excludes every DOM/JS escape hatch
(`browser_evaluate`, `browser_html`, `browser_snapshot`, `browser_console`,
`browser_get_text`, `browser_shadow_query`). She
has only `browser_screenshot` plus coordinate-based `browser_interact`. To
get a comparable upper bound, run the same eval with a default queen
(e.g. `queen_technology`) — the gap measures how much vision actually
contributes to her interaction success rate.

## Layout

```
server.py        # stdlib http.server, route handlers, JSONL log writer
static/
  style.css      # shared CSS for task pages and the report
  instrument.js  # Eval.* helpers (markSuccess / markMiss / requireClickOn)
tasks/           # one HTML page per challenge (10)
runs/            # appended per-run event logs
```

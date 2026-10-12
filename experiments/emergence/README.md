# The Vale of Ashmere

An emergence experiment: fifteen language-model villagers in a medieval valley,
powered by nothing but a dawn tick.

Nothing coordinates the villagers. There is no orchestrator, no queen, and no task
list. Each agent has a persona (its system prompt), a few rules it lives by that
interlock with other people's, and a private `memory.md` it rewrites every time it
acts. Cheap physics, with no model calls, decides **who** is stirred to act; the
model decides **what** they do. A hidden world (a poisoned river, wolves, an old
song) shows itself only through omens, through what villagers find when they look
closely, and through the outcomes of what they attempt together.

## Running it

From this directory, with no dependencies beyond the standard library:

```sh
uv run --no-project python -m vale new myrun            # copy the world template into runs/myrun
uv run --no-project python -m vale tick myrun           # one day: this is what a cron calls
uv run --no-project python -m vale run myrun --days 14  # a cron in miniature
uv run --no-project python -m vale stats myrun          # ripples, branching ratio, ties
uv run --no-project python -m vale chronicle myrun      # a chronicler writes the run up
uv run --no-project python -m vale report out.html --run "myrun:Label" [--run ...]
uv run --no-project python -m vale report zh.html --lang zh --run "myrun:标签"  # Chinese, model-translated, cached in runs/_i18n
uv run --no-project python -m vale sweep                # tune the physics with dice, no model
```

Every `tick` loads `runs/<name>/state.json`, plays one dawn-to-night day, and saves it
again, so a real cron (or Task Scheduler) can drive a vale forever. The model endpoint
is any OpenAI-compatible API: `VALE_API_BASE` (default `http://127.0.0.1:8790/v1`),
`VALE_MODEL` (default `gpt-6.1-sol`), `VALE_API_KEY`.

Physics knobs live in `world/world.toml` under `[physics]`; override them per run with
`new myrun --set refill=1.0 --set theta_scale=1.6`.

## How a day works

- **Dawn (the cron's whole contribution).** The hidden world advances a night. Each
  villager's energy reserve is topped up by `refill`, up to `reserve_cap`. The world
  shows its omens, and any undertaking set for dawn is attempted.
- **Six waves: dawn, morning, midday, afternoon, dusk, night.** In each, every villager
  attends to the signals around them: the strongest fully, the next half, and so on.
  Each signal is weighted by how loud it still is, how much its topics matter to them,
  whether it names them, and whether it comes from someone they love or resent. They
  stir with probability S² / (S² + θ²), and stirring costs one unit of reserve.
- **Stirred villagers act at once,** like a generation of the Game of Life. One model
  call each returns up to three actions (say, look, post, paint, give, work, tend,
  propose, join, oppose, travel) and a rewritten memory.
- **Word travels.** Speech is heard only where it is spoken. Strong signals travel one
  road per wave as rumour, weaker each hop. Worked-up speakers are louder, so alarm
  travels and idle talk stays local. Notices and paintings hang for days.
- **Night.** Topics a villager acted on sharpen their attention, and the rest drift
  back. Faint signals fade. Memory files are snapshotted.

## Three gods (optional)

The vale's lore has three gods. **Ullr**, the old god of the hills, owns the Seven Stones;
his power has waned as faith turned away, which is why the binding loosened, and the
shepherd's song sung at dusk wakes his authority for a few nights (`ullr_awake`). He is
never an agent. The other two can be:

- **The True God** (`--set god_grace=1`; `vale/god.py`, prompt in `world/god.md`). It
  loves the vale's people, does not want Ullr to wake, and is wary of the Outer God.
- **pleiades, the Star God** (`--set outer_god=1`; `vale/outer.py`, prompt in
  `world/outer_god.md`), Bagel's master. When she prays to him he may grant a boon where
  she stands (heal, cleanse, mend, drive off wolves, give a needed thing), taking one of
  her paintings as the price. His miracles ease symptoms and never touch the binding.

`world/truth.md` is read by fate, the True God and the chronicler; `world/truth_deep.md`
holds what even the True God cannot see, and only fate and the chronicler read it.

Once each dawn the True God reads everything: the hidden truth, every villager's memory
file, the day's words and deeds, and their prayers. It has two powers:

- **The Ledger of the World.** The god rewrites it each dawn, and every villager sees it
  whenever they act. Every line must cite signals a villager said, posted, did or found,
  or that the world plainly showed someone. The engine strikes any line whose citations
  don't check out, and shows villagers who witnessed each line.
- **Grace.** One unit a dawn, saved up to `god_grace_cap`. Each unit buys a dream (one
  villager, under sixty words) or a sign (a wonder at one place).

It cannot change the world itself. Villagers gain a `pray` action that only the god hears.
You can also play god by hand; these take effect at the run's next dawn:

```sh
uv run --no-project python -m vale god myrun dream tobias "Seven stand; one lies. Read what is cut there."
uv run --no-project python -m vale god myrun sign barrow_hill "At dusk the six standing stones hum."
uv run --no-project python -m vale god myrun ledger "The water below Greyfang runs red."
```

**Undertakings** are the only way villagers change the world. Anyone can propose one,
naming where the work is done and at which part of the day; others must go to where it
is posted to join or oppose it. At quorum it is attempted at that place and hour (today
if the hour is still to come, otherwise tomorrow). Supporters at the site, or one road
from it, take part; the rest are counted as absent. An impartial fate that knows the
hidden truth decides what happens, counting the crafts, authority and goods of those
present, and can change the world only through a fixed list of effects.

## Layout

```
world/                 the template: places, clues, omens, calendar, physics, the cast
  truth.md             the hidden truth (only fate and the chronicler read it)
  rules.md             how the world works, shown to every villager
  agents/<id>/         persona.md (system prompt), memory.md (starting memory), sheet.toml
vale/                  the engine (stdlib only)
  physics.py           stirring, energy, attention, rumour, adaptation (no model)
  nature.py            the hidden world: blight, sickness, wolves, omens
  mind.py              villager prompts; StubMind rolls dice instead
  act.py               applying actions
  fate.py              resolving undertakings against the hidden truth
  engine.py            one tick
report/template.html   the visual report
runs/<name>/           a run: frozen world copy, state.json, log.jsonl, agents/*/memory.md
```

## What happened

See the report built from `runs/vale1` (0.6 energy per dawn) and `runs/vale2` (1.0 per
dawn): `python -m vale report report.html --run "vale1:Little power" --run "vale2:More power"`.

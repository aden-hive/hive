# Writing a world

The vale engine runs any world a story pack describes. The engine is the **kernel**: the parts
every world shares, which are how a world evolves and how its people work together. The **story
pack** holds everything that makes one world different from another. A pack is data only: TOML,
Markdown and expressions in a small, safe language. Writing a new world needs no Python.

Two worlds ship with the engine, and both use the same kernel:

- `stories/ashmere/`: a dark one. A blighted river, a sealed mine, wolves, a sleeping god and a
  scheming steward.
- `stories/glimmer/`: a bright one. An island relights its lighthouse from seven scattered prisms,
  mends an old feud, and gets ready for Lantern Night so its children can sail home.

Read both `rules.toml` files next to this document; they are the best examples.

## What the kernel does, and what a world declares

| | The kernel (the same in every world) | The world (`stories/<story>/`) |
|---|---|---|
| **Time** | Days of six parts (dawn to night). Dawn runs in a fixed order (see *The day*). | What happens each night and dawn: the `night`, `dawn`, `after_gods` and `watch` hooks. |
| **Hidden state** | A dict that is saved with the run. The kernel keeps a few names for itself (see *Reserved names*). | Every other name: `[state]`, and whatever the hooks and effects write. |
| **Signals** | Speech, notices, omens, signs, dreams, rumours. Each has a place, a strength and an audience. They spread one road per part of the day and fade. | Omens, calendar days, the chance deck and the places (`world.toml`). Events and signals emitted by the rules. |
| **Attention** | The physics of who stirs. Each villager has an energy reserve, a threshold (`theta`), interests that are weights on topics, habituation, learning and diffusion. Dawn is the only source of new energy. | The topics and the words that raise them (`[lexicon]`), each person's interests, and physics overrides. |
| **Villagers** | Each one is a Hive agent with a persona, private notes and tools. The tools let them say, go, look, post a notice, give, work, attempt, propose, join, oppose and pray. | Who they are (`agents/`), what each trade makes (`[professions]`), what goods are called (`[items]`), and extra actions such as `tend`. |
| **Collaboration** | Undertakings: someone proposes one at a place and an hour, others join or oppose. The hour is never sooner than the proposer can get there. Whoever joined walks toward the site in time, one road per part, and whoever comes is gathered. Fate weighs skills, items, knowledge and helpers. The dice decide on a five-band scale (critical, success, partial, failure, fumble). | What fate may change: the world's own effects (`[effects.<type>]`) and their conditions. |
| **Knowledge** | Facts a person knows, which are passed to fate; things found by looking closely. | The facts (`[knows]`), and which features grant them (`grants`). |
| **Gods** | Three kinds of god, each a module configured by data. `ledger` keeps the shared ledger and spends grace on dreams and signs. `patron` answers one follower's prayers with boons. `sleeper` acts only while it is awake. | Which gods this world has, in what order, and their settings (`[[god]]`). |
| **The One Above** | The player. They have an awe economy, tiers, a queue of powers and chapters. There are six standard power blocks. | Its powers (a standard block, or the world's own steps), its chapters and its awe numbers. |
| **Telling** | The host stages each part of the day as beats, and the novelist writes each day as a chapter. | The premise, and the words in every language. |
| **Pictures** | Portraits and scene drawings built from parts. The map, the panorama, water, glow and marks. | Each person's look and each place's kind (`art.toml`). What the panel and scene show (`[panel]`, `[scene]`). |

The rule of thumb: **if two worlds would both need it, it belongs in the kernel; if only one
world would, it belongs in that world's data.** When a new world needs something the kernel
cannot express, add a general mechanism to the kernel, such as a new step key or a new rule
function. Never add a special case for that world.

## A story pack

```
stories/<story>/
  rules.toml              mechanics, in no language: state, hooks, effects, powers, chapters, gods, panel, scene
  art.toml                pictures, in no language: each person's portrait, each place's kind, the map, the panorama
  <lang>/                 one folder per language (en, zh, ...); every language has the same keys
    world.toml            places, features and views, omens, the calendar, the deck, weathers, physics
    story.toml            every word the story says that the engine does not
    rules.md              the rules of the world, as the villagers are told them
    truth.md              the hidden truth, as fate, the gods and the host are told it
    god.md, god_rules.md  the ledger god's persona and rules ({lines} is filled in)
    agents/<id>/
      persona.md          who they are, how they speak, what they want and fear, their secrets, their rules
      sheet.toml          name, role, home, profession, theta, items, skills, interests, ties, knows
      memory.md           their private notes at the start
```

A new run copies the language folder, `rules.toml` and `art.toml` into `run/world/`, so a run
keeps the rules it started with. A story is listed in the game once it has a folder with a
`story.toml`.

## The day

Each day has six parts. The game steps through them one at a time.

**Dawn** (part 0, before anyone stirs):

1. The player's queued powers are applied.
2. Each villager's reserve is topped up by `physics.refill × rules.refill`.
3. The night passes (from day 2 on): the world's **`night`** steps run.
4. Undertakings set for dawn are attempted.
5. The world shows itself, in this order: the weather; the **events** queued in the night;
   omens whose conditions hold; the calendar; one card from the chance deck; then the world's
   **`dawn`** steps.
6. The gods take their turns, in the order `[[god]]` lists them.
7. The world's **`after_gods`** steps run.
8. The One Above's dawn: awe income, and prayers answered with awe.

**Each part of the day:**

1. Travellers arrive.
2. Whoever joined an undertaking set for later today, and is more than one road from its site,
   sets off toward it. This costs no energy and no model turn.
3. Undertakings whose hour has come are attempted with whoever came. Anyone one road away is
   gathered in.
4. Whoever the physics stirs acts as a Hive agent. Under `pace`, the loudest call goes first.
5. Lone attempts are settled by the dice.
6. Strong signals travel one road.
7. The world's **`watch`** steps run, then the chapters are checked.

**Night** (after the last part):

1. Sensitivities drift.
2. Faint signals fade.
3. Memories are snapshotted.
4. The day's summary is logged. Its `hidden` field is the world's `summary` keys.

## rules.toml

### Expressions

Every value in `rules.toml` that does something is an **expression**. Expressions are a
Python-like language, parsed with `ast` and checked against a whitelist (`rules/expr.py`). They
have no `eval`, no attributes starting with `_`, no imports, no lambdas and no calls except to
the functions listed below. Every expression is parsed when the world loads, so a broken world
fails at start rather than in the middle of a game.

You can use literals, lists, dicts, tuples, comprehensions, `a if c else b`, `and`, `or` and
`not` (both short-circuit, so a `chance()` in a condition rolls only when it is reached),
comparisons, `in`, arithmetic, subscripts and `.key` on dicts.

**Names** are resolved in this order:

1. Locals: from `let`, `for`, an effect's arguments, or a power's arguments.
2. `[constants]`.
3. Villager fields, read by id: `health[who]`, `loc[who]`, `home[who]`, `items[who].rope`,
   `confined[who]`, `ties[who]`, `reserve[who]`, `skills[who]`, `knows[who]`.
4. Special names: `day`, `wave`, `places` (ids), `villagers` (ids), `state` (the whole hidden
   dict), `prev` (the hidden state as the hook began) and `overgod` (the One Above's state, for
   example `overgod.ever.prayed`).
5. Hidden state. **A name that is missing reads as 0**, so a flag needs no declaration.

**Functions:**

| | |
|---|---|
| Python | `min max abs round int float str len list sorted sum bool any all set` |
| Numbers | `clamp(x, lo=0, hi=1)` (rounded to 4 places), `pct(x)` → `"42%"`, `bucket(x, *cuts)` → the index of the first cut that `x` is below |
| Dice | `rand()`, `chance(p)`, `pick(items)`. All use the run's seeded RNG, so a run replays exactly. |
| State | `has(name)`, `get(d, key, default=0)` |
| The world | `present(place)` (ids there), `here(who)`, `name(id)`, `short(who)`, `place_name(id)`, `resolve_place(text)`, `resolve_person(text)` (id or None), `goods(text)` (an item id from any of its names) |
| Words | `say('dotted.key', **slots)` reads the story's `story.toml` and fills slots such as `{world}`. `t('key', **slots)` reads the engine's phrases. `fill(template, **slots)`. `join(sep, items)`. |

### Steps

Hooks, effects and the world's own powers are made of **steps**. A step is a table, and its keys
run in this order:

| key | what it does |
|---|---|
| `let` | Bind local names: `{ amount = "min(0.5, arg.amount)" }`. |
| `when` | A condition. If it fails, the rest of the step is skipped and `else` runs instead. |
| `else` | A step, or a list of steps, run when `when` fails. |
| `for` | `"x in expr"` or `"k, v in expr"`. The rest of the step runs once for each item. |
| `set` | Targets to values, in order. A target is a name (hidden state, or a local if one exists), `name[key]`, `name.key`, or a villager field such as `"items[who].prism"`. Missing dicts on the way are created. |
| `delete` | Targets to remove. |
| `push` | Append to a list: `{ deaths = "who" }`. |
| `event` | `{ place, text, strength = 2.8 }`: an omen queued for the next dawn. Use it for what the night did. |
| `emit` | `{ text, place?, strength = 2.6, kind = 'omen', audience?, source? }`: a signal now. Use it for what dawn shows, or what a power does. |
| `do` | Sub-steps, in order, in the same scope. |

```toml
# Ashmere: each night the blight spreads downstream from wherever the shaft is open.
[[night]]
for = "place, level in blight.items()"
when = "level > 0.2 and chance(level)"
set = { "sickness[place]" = "clamp(get(sickness, place) + 0.05 * level)" }
```

### Sections

**`[state]`** holds the hidden world's starting values, beyond those in `world.toml`. The names
must not be reserved.

**`[constants]`** holds named data the rules read: tables, ids and thresholds. The kernel reads
one constant itself: `jail`, the place a `confine` effect sends a villager to.

**`[[night]]`, `[[dawn]]`, `[[after_gods]]`, `[[watch]]`** are lists of steps, run at the moments
described in *The day*.

**`refill`** is an expression giving the share of each dawn's energy that reaches the villagers
(default 1). **`travel`** is how many parts of the day one road takes (default 1). Ashmere uses
both for its hard winter.

**`describe`** is a list of expressions, one line each, giving the hidden world in words. Fate,
the gods, the host and the novelist read it. Empty lines are dropped.

**`summary`** lists hidden keys to keep in each day's record.

**`[effects.<type>]`** declares what fate may change in this world, beyond the standard effects.
Fate is told each effect's words from `story.toml [fate] effects`. Each effect has these keys:

- `need`: the arguments it must have. A missing one is logged as a bad effect.
- `let`: binds locals. The scope has `arg` (the effect as fate wrote it), `present` (the ids at
  the place) and `site` (the place).
- `requires`: a condition. If it fails, the effect is refused and fate's story stands without it.
- Then any step keys.

The standard effects, which every world has, are `item`, `health`, `confine`, `tie` and `reveal`.

```toml
# Glimmer: a prism fitted back into the lens frame. Only someone carrying a prism can do it.
[effects.set_prism]
need = ["who"]
let = { who = "resolve_person(arg.who)" }
requires = "who and get(items[who], 'prism', 0) >= 1 and lens < 7"
set = { "items[who].prism" = "items[who].prism - 1", lens = "lens + 1" }
```

**`[[power]]`** declares the One Above's powers. Each needs `id`, `tier`, `cost` and `params`.
Parameters are named by kind: `to`/`who` is a person, `at` is a place, and `text`, `god` and
`days` are what they say. A power then does one of two things:

- `use` names a standard block: `whisper`, `inscribe`, `sign`, `prophecy`, `reveal` or `decree`.
- `steps` runs the world's own steps, with the parameters as locals. `done` is an expression
  for the line the player sees.

A power's name and description are in `story.toml [overgod] powers`.

**`[[chapter]]`** declares the One Above's goals. Each has `id`, `when` (a condition), `reward`
(awe) and an optional `unlocks` (a tier). Chapters are checked after each part of the day, in
order. Titles are in `story.toml [overgod] chapters`.

**`[awe]`** sets the One Above's economy. The keys and defaults are `start = 3`, `cap = 12`,
`dawn = 1`, `prayer = 1`, `prayers_max = 3`, `drama = 0.5` and `drama_max = 2`.

**`[[god]]`** lists the gods, in the order they take their dawn turns. Each has an `id` and a
`kind`:

- `ledger`: keeps the shared ledger and spends grace on dreams and signs. It needs no settings.
  Its persona is `god.md`.
- `patron`: answers its one follower's prayers with boons, and may be paid in offerings. It
  takes these settings:
  - `switch`: the physics key that turns it on.
  - `follower`.
  - `words`: the `story.toml [gods]` key listing the words that address it.
  - `to`: the prayer target.
  - `prayers`: the hidden key for its prayers.
  - `offering`: the signal kind it accepts.
  - `bound`: a condition under which the One Above has bound it.
  - `gifts`: item ids.
  - `boons`: a dict of named expressions, each producing an effect. They may use `here` and `who`.
- `sleeper`: acts only while awake, or stirring. It takes these settings:
  - `switch`, `words`, `to`, `prayers`.
  - `awake` and `stirring`: expressions.
  - `song`: the effect type that wakes it.
  - `high_places`: where it can be met.
  - `hunt`: a once-only intervention, with `once`, `at`, `strength` and `steps`.

**`[actions.<verb>]`** adds a world-specific villager action. The kernel knows `tend`, which uses
an item and a skill: the dice band picks `[count, amount]` from `by_band`, then `steps` run with
`here` and `amount` bound. The tool is offered only when the world declares it.

**`[physics]`** overrides `world.toml`'s physics for games of this world, for example
`ullr_agent = 0` when the world has no sleeper.

**`[panel]`** sets what the player's truth panel shows. It has two lists:

- `[[panel.fact]]`: `label`, `text`, `tone`.
- `[[panel.bar]]`: `label`, `value` (0 to 1), `text`, `tone`.

Each entry may have `when` and `for`. A tone is `'good'`, `'bad'` or `''` (plain). The labels come
from `say('panel.…')`.

**`[scene]`** sets what the pictures read. It has three expressions:

- `water`: per place, 0 to 1. How murky its stream looks.
- `glow`: per place, 0 to 1. Lanterns and lit windows.
- `marks`: named flags the art knows, such as `deep_door`, `stone_raised`, `awake`, `winter`
  and `ebb`.

### Reserved names

The kernel keeps these hidden names for itself, and a world's `[state]` may not use them:
`clock today events fired_today weather weather_kind overgod ledger ledger_pinned grace god_human
host_last prayers prayers_overgod taken counters`. The check runs at load, with a clear error.
Glimmer's lens clockwork is called `clockwork` for this reason.

## world.toml (per language)

- **`[vale]`** has `name`, `season`, `weathers` (a list of sentences) and `weather_kinds` (in the
  same order, for the pictures: `fog`, `showers`, `rain` and `wind` are drawn; anything else, such as
  `clear` or `overcast`, is drawn plain).
- **`[physics]`** holds the attention numbers (see `physics.py`), and `[physics.kinds]` gives the
  `[strength, decay]` of each signal kind. `pace` spreads the day's acts over the day. At 0,
  everyone spends their energy on the first thing that stirs them, so afternoons go quiet. Above
  0, the acts left in the village are shared out over the parts of the day still to come, times
  `pace`; the loudest call is answered first, and the rest keep their energy for later. Live
  games use 1.5.
- **`[[place]]`** has `id`, `name`, `desc`, `x`/`y` on a 0 to 100 map, and `roads`. Each
  `[[place.feature]]` has an `id` and a `name`, and a list of `[[place.feature.view]]`, each with
  an optional `when` and a `text`. The first view whose `when` holds is the one seen. A feature
  (or a view) may have `grants = "<knows id>"`: whoever looks closely learns that fact.
- **`[[omen]]`** has `id`, `place`, `when`, `every` (days between showings), `strength`, `text`,
  and an optional `who` (an audience).
- **`[[calendar]]`** has `day`, `place` (or `"*"` for everywhere), `strength` and `text`.
- **`[[deck]]`** has `place`, `min_day`, an optional `when`, `strength` and `text`. Each dawn
  there is a 60% chance one unused card is drawn.

In `world.toml`, `when` is a list of `[name, op, value]` triples over the hidden state, and all of
them must hold. These are plain conditions that a translator can read. They are not expressions.

## story.toml (per language)

This file holds every word the story says that the engine does not. Every language must have the
same keys.

- **`[story]`**:
  - `id`, `lang`, `title` and `blurb`.
  - `world`: what the world is called mid-sentence, such as "the vale" or "the isle". It fills
    `{world}`, `{World}` and `{WORLD}` in the engine's phrases.
  - `premise`: the host's one-line sense of the game.
  - `river`: one line about the land.
- **`[gods]`** has `names` (`world`, `god`, `overgod`), `titles`, `above_words` (the words that
  pray to the One Above) and each god's words. `[gods.pray]` gives the prayer targets as the
  villagers see them.
- **`[persona]`** gives the headings of the persona sections the engine looks for (want, rules,
  deeper).
- **`[place_aliases]`**, **`[professions.<id>]`** (`hint`, `makes`, `deed`), **`[items]`** (`name`,
  `aliases`, and regex `match`es), **`[lexicon]`** (topic → words) and **`[knows]`** (fact id →
  what fate is told).
- **`[fate] effects`** describes every effect type to fate, the world's own and the standard ones.
- **`[state]`** and **`[nature]`** hold the words the rules' `say()` reads.
- **`[overgod]`** holds power and chapter names, power texts, and `[overgod.secrets]` (one per
  person, for `reveal`).
- **`[panel]`** holds the words for the panel.
- **`[phrases.<section>]`** overrides any engine phrase for this story.

## Agents

There is one folder per person, under each language.

`sheet.toml` holds:

- `name`, `short`, `role`, `public` (what everyone knows), `home`, `start` and `profession`.
- `theta`: how hard they are to stir.
- `aliases`.
- `[items]` and `[skills]` (out of 100: strength, craft, lore, song, healing, hunting, arms,
  magic, persuade, stealth, trade, notice).
- `[interests]`: topic → weight.
- `[ties]`: person → −1..1.
- `knows`.
- `health`.

`persona.md` is written to the person as "you". `memory.md` is their private notes at the start.
A person with a secret, a want and a fear will act. Give at least one person a real conflict of
interest; a world where everyone wants the same thing goes quiet.

## art.toml

Each person gets `color`, and their portrait parts: `skin`, `hair`, `style`, `beard`, `hat`,
`coat`, `trim`, `age` and `extras`. Alternatively, a person can have `image = "people/x.png"`.

Each place gets a `kind`, which picks its picture. The kinds are:

- `mine`, `keep`, `mill`, `village`, `chapel`, `stones`, `pasture`, `forest`, `ford`
- `lighthouse`, `harbor`, `orchard`, `garden`, `cave`

`[map]` may draw a `coast` and `streams`/`floods`. `panorama` picks the dawn backdrop (`vale`
or `isle`). The art kinds are a library in the frontend. A new kind is one more drawing there,
which every later world can use.

## Making a new world

1. Copy the layout above. Start with `rules.toml`:
   - what the world is trying to become (the state, and the chapters);
   - what pushes back each night;
   - what fate may change;
   - and what the One Above can do.
2. Write the places, with features whose views change with the state, and hide the clues in
   `grants`.
3. Write the people. Spread what is needed across them (items, skills, knowledge) so that
   nobody can finish alone.
4. Write `truth.md`, so that fate, the gods and the host know what is really going on.
5. Check it without a model. Create a world, apply each effect, run the hooks for a few nights,
   check the chapters and powers, and print `describe`, the panel and the scene
   (`tests/test_vale.py` has an island example). Then play a few days live.
6. Add the second language by translating every value under the same keys.

### What is still code

- **The three god kinds.** They are modules configured by data. A fourth kind of god is a new
  module.
- **The six standard power blocks and the five standard effects.**
- **The art kinds.** They are a drawing library, chosen by data.
- **The `tend` action.** It is the one world-specific action shape so far.

Everything a world *decides* is data.

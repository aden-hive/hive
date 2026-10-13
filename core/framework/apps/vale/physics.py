"""The cheap rules: who is stirred, when, and how far word travels.

No language model runs here. Every wave, each villager attends to the signals they
can perceive — the strongest fully, the next half, the next a quarter — each weighted
by how loud it still is, how much its topics matter to them, whether it names them or
comes from someone they care about, and how often they've already acted on it — and
stirs with probability S² / (S² + θ²). Stirring
spends stored reserve, which only the dawn refills: the vale can never do more than
the dawns pay for.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from .lexicon import mentions
from .world import WAVE_LEN, WAVES, Agent, Signal, World


@dataclass
class Firing:
    agent: str
    stimulus: float
    p: float
    contribs: list[tuple[str, float]]  # (signal id, contribution), strongest first
    parent: str | None  # activation that caused the strongest signal (None: the world)
    tags: list[str] = field(default_factory=list)


def arousal(stimulus: float) -> float:
    """How loudly a stirred villager speaks: the more worked up, the further it carries."""
    return max(0.8, min(1.5, 0.75 + 0.1 * stimulus))


def relevance(agent: Agent, sig: Signal) -> float:
    r = 0.15 + sum(agent.interests.get(t, 0.0) for t in sig.tags)
    if sig.to == agent.id:
        r += 2.0
    elif mentions(sig.text, agent.aliases):
        r += 1.2
    tie = agent.ties.get(sig.source)
    if tie:
        # Love and grudges both make a voice hard to ignore.
        r += 0.4 * abs(tie)
    return r


def visible(world: World, agent: Agent) -> list[Signal]:
    out = []
    for sig in world.signals.values():
        if sig.source == agent.id:
            continue  # your own words don't stir you
        if sig.audience is not None:
            if agent.id in sig.audience and (sig.loc is None or sig.loc == agent.loc):
                out.append(sig)
        elif sig.loc is not None and sig.loc == agent.loc:
            out.append(sig)
    return out


def stimulus(world: World, agent: Agent) -> list[tuple[str, float]]:
    now, hab = world.now, world.params["habituation"]
    out = []
    for sig in visible(world, agent):
        level = sig.level(now)
        if level < 0.05:
            continue
        c = level * relevance(agent, sig) * hab ** agent.attended.get(sig.id, 0)
        if c >= 0.02:
            out.append((sig.id, c))
    out.sort(key=lambda x: -x[1])
    return out


def _cap(world: World, agent: Agent) -> int:
    return 1 if agent.health >= 2 else int(world.params["max_acts_per_agent"])


def _pace(world: World, cost: float) -> int | None:
    """How many may stir in this part of the day, so the day's energy lasts the day (``pace``; None: no limit).

    Left alone, everyone spends their day on the first thing that stirs them at dawn, and the
    afternoon and evening fall silent while people are still being stirred. With ``pace``, the
    acts still left in the village are spread over the parts of the day still to come, times
    ``pace`` so a busy morning can still be busy.
    """
    pace = float(world.params.get("pace", 0.0))
    if pace <= 0:
        return None
    left = sum(
        max(0, min(_cap(world, a) - a.acts_today, int(a.reserve // cost))) for a in world.agents.values() if a.loc is not None and not a.confined
    )
    return math.ceil(pace * left / (len(WAVES) - world.wave))


def select(world: World) -> list[Firing]:
    """Who stirs this wave. Mutates reserves, counters and habituation of the stirred."""
    p = world.params
    cost = p["activation_cost"]
    room = int(p["max_activations_per_day"]) - world.today["activations"]
    limit = _pace(world, cost)
    ids = sorted(world.agents)
    world.rng.shuffle(ids)
    stirred: list[tuple[Agent, float, float, list[tuple[str, float]]]] = []
    for aid in ids:
        if len(stirred) >= room:
            break
        a = world.agents[aid]
        if a.loc is None or a.confined > 0 or a.acts_today >= _cap(world, a) or world.wave - a.last_wave < 1:
            continue
        contribs = stimulus(world, a)
        # Attention, not a sum: the loudest thing counts fully, the next half...
        s = sum(c * 0.5**i for i, (_, c) in enumerate(contribs))
        if s <= 0:
            continue
        theta = a.theta * p["theta_scale"]
        prob = s * s / (s * s + theta * theta)
        if world.rng.random() >= prob:
            continue
        if a.reserve < cost:
            # Stirred, but spent: the clearest place to see the energy budget bite.
            world.today["tired"] += 1
            world.log("tired", agent=aid, stimulus=round(s, 2), reserve=round(a.reserve, 2))
            continue
        stirred.append((a, s, prob, contribs))
    if limit is not None and len(stirred) > limit:
        stirred.sort(key=lambda x: -x[1])  # the loudest call is answered first; the rest keep their energy for later
        for a, s, _, _ in stirred[limit:]:
            world.today["waiting"] = world.today.get("waiting", 0) + 1
            world.log("waiting", agent=a.id, stimulus=round(s, 2))
        stirred = stirred[:limit]
    return [_fire(world, a, s, prob, contribs, cost) for a, s, prob, contribs in stirred]


def _fire(world: World, a: Agent, s: float, prob: float, contribs: list[tuple[str, float]], cost: float) -> Firing:
    a.reserve -= cost
    a.acts_today += 1
    a.last_wave = world.wave
    a.total_acts += 1
    for sid, _ in contribs:
        a.attended[sid] = a.attended.get(sid, 0) + 1
    top_c = contribs[0][1]
    caused = next((world.signals[sid] for sid, c in contribs if world.signals[sid].cause and c >= 0.5 * top_c), None)
    parent = caused.cause if caused else None
    tags = Counter(t for sid, _ in contribs[:3] for t in world.signals[sid].tags)
    return Firing(a.id, round(s, 3), round(prob, 3), [(sid, round(c, 3)) for sid, c in contribs[:8]], parent, [t for t, _ in tags.most_common(4)])


# ---------------------------------------------------------------------------- word travels


def _rumor_text(world: World, sig: Signal) -> str:
    t = world.t
    place = world.place_name(sig.loc)
    who = world.name(sig.source)
    body = sig.text if len(sig.text) <= 240 else sig.text[:237] + "..."
    if sig.kind in ("speech", "notice", "painting"):
        return t(f"mind.rumor_{sig.kind}", place=place, who=who, text=body)
    if sig.kind == "project":
        proj = world.projects.get(sig.project or "")
        if proj:
            return t("mind.rumor_project", place=place, title=proj.title, goal=proj.goal, needs=proj.needs)
    if sig.kind == "rumor":
        return t("mind.rumor_rumor", place=place, text=body.split(": ", 1)[-1].split("：", 1)[-1])
    return t("mind.rumor_other", place=place, text=body)


def diffuse(world: World) -> int:
    """Strong public signals travel one road per wave, weaker each hop."""
    p = world.params
    now = world.now
    spawned = 0
    for sig in list(world.signals.values()):
        if sig.diffused or sig.loc is None or sig.audience is not None or sig.kind in ("arrival", "deed"):
            continue
        if sig.hops >= p["diffusion_hops"]:
            continue
        level = sig.level(now)
        if level < p["diffusion_min"]:
            continue
        sig.diffused = True
        text = _rumor_text(world, sig)
        for road in world.places[sig.loc]["roads"]:
            world.add_signal(
                "rumor",
                text,
                road,
                sig.source,
                tags=list(sig.tags),
                cause=sig.cause,
                strength=round(level * p["diffusion_factor"], 3),
                born=now + WAVE_LEN,
                hops=sig.hops + 1,
                origin=sig.origin or sig.id,
                project=sig.project,
            )
            spawned += 1
    return spawned


# ---------------------------------------------------------------------------- dusk


def adapt(world: World, firings: list[Firing]) -> None:
    """Acting on a topic sharpens you to it; otherwise you drift back to yourself."""
    lr, ur = world.params["learn_rate"], world.params["unlearn_rate"]
    for f in firings:
        a = world.agents[f.agent]
        for t in f.tags:
            a.interests[t] = round(min(1.8, a.interests.get(t, 0.0) + lr), 3)
    for a in world.agents.values():
        for t in list(a.interests):
            target = a.base.get(t, 0.0)
            a.interests[t] = round(a.interests[t] + ur * (target - a.interests[t]), 3)
            if a.interests[t] < 0.01 and target == 0:
                del a.interests[t]


def cleanup(world: World) -> int:
    """Forget signals too faint to stir anyone (they stay in the log)."""
    later = world.now + WAVE_LEN
    dead = []
    for sid, sig in world.signals.items():
        if sig.kind == "project":
            proj = world.projects.get(sig.project or "")
            if proj and proj.status in ("open", "due"):
                continue
        if sig.level(later) < 0.05:
            dead.append(sid)
    for sid in dead:
        del world.signals[sid]
    alive = set(world.signals)
    for a in world.agents.values():
        a.attended = {k: v for k, v in a.attended.items() if k in alive}
        a.heard = [h for h in a.heard if h in alive][-12:]
    return len(dead)

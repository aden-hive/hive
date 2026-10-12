"""The report in another language: run data translated by the model (cached), and the
page's own words swapped at build time. Simplified Chinese ("zh") only, for now.

The English template stays the source of truth. Every UI replacement names an exact
English string in it, and the build fails if that string has gone missing, so the
Chinese page can't quietly fall back to English when the template changes.
"""

from __future__ import annotations

import copy
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .export import displayed_signals
from .llm import LLM, parse_json_object

NAMES_ZH = {  # id: (name, short name)
    "hal": ("哈尔·韦恩赖特", "哈尔"), "maud": ("莫德·芬纳", "莫德"), "aldric": ("奥德里克·索恩爵士", "奥德里克"),
    "osric": ("奥斯里克·维恩", "奥斯里克"), "brannoc": ("布兰诺克·邓恩", "布兰诺克"), "isolde": ("伊索尔德嬷嬷", "伊索尔德"),
    "gytha": ("吉莎", "吉莎"), "bram": ("老布拉姆", "布拉姆"), "wynn": ("温·布兰布尔", "温"),
    "tobias": ("托拜厄斯·奎尔", "托拜厄斯"), "marta": ("玛尔塔·霍洛韦", "玛尔塔"), "cedric": ("塞德里克·阿什比", "塞德里克"),
    "elspeth": ("埃尔斯佩丝·罗", "埃尔斯佩丝"), "kell": ("凯尔", "凯尔"), "bagel": ("贝果", "贝果"),
}
PLACES_ZH = {
    "mine": "灰牙矿", "thornkeep": "荆堡", "mill": "空溪磨坊", "ashmere": "灰湖", "chapel": "圣文娜礼拜堂",
    "barrow_hill": "古冢丘", "fold": "牧人羊圈", "mirewood": "沼林", "fenford": "芬渡",
}
EFFECTS_ZH = {
    "seal_shaft": "封上深门", "reopen_shaft": "重开深门", "raise_stone": "立起石头", "sing": "唱起牧歌",
    "purify": "净水", "heal": "疗愈", "wolves": "狼群", "item": "物品", "health": "健康", "confine": "关押",
    "tie": "情谊", "reveal": "揭示",
}
STRUCK_ZH = {"uncited": "未引用", "over the limit": "超出上限"}

GLOSSARY_ZH = """Places: Vale of Ashmere = 灰湖谷; Ashmere = 灰湖; Ashmere green = 灰湖草坪; Greyfang Mine = 灰牙矿; Greyfang = 灰牙;
Hollowbrook Mill = 空溪磨坊; the Hollowbrook = 空溪; millrace = 磨坊水道; Thornkeep = 荆堡; Barrow Hill = 古冢丘; the barrow = 古冢;
Saint Wenna's Chapel = 圣文娜礼拜堂; Saint Wenna = 圣文娜; Shepherd's Fold = 牧人羊圈; the Fold = 羊圈; Mirewood = 沼林;
Fenford = 芬渡; the Drowned Lantern = 溺灯酒馆; the Lantern = 溺灯.
People: Hal Wainwright = 哈尔·韦恩赖特 (Hal = 哈尔); Pip = 皮普; Maud Fenner = 莫德·芬纳 (Maud = 莫德);
Ser Aldric Thorne = 奥德里克·索恩爵士 (Ser Aldric = 奥德里克爵士, Aldric = 奥德里克); Osric Vane = 奥斯里克·维恩 (Osric = 奥斯里克);
Brannoc Dunn = 布兰诺克·邓恩 (Brannoc = 布兰诺克); Mother Isolde = 伊索尔德嬷嬷 (Isolde = 伊索尔德); Gytha = 吉莎;
Old Bram = 老布拉姆 (Bram = 布拉姆); Wynn Bramble = 温·布兰布尔 (Wynn = 温); Tobias Quill = 托拜厄斯·奎尔 (Tobias = 托拜厄斯);
Marta Holloway = 玛尔塔·霍洛韦 (Marta = 玛尔塔); Cedric Ashby = 塞德里克·阿什比 (Cedric = 塞德里克);
Elspeth Rowe = 埃尔斯佩丝·罗 (Elspeth = 埃尔斯佩丝); Kell = 凯尔; Bagel = 贝果; Ned = 内德; Cob = 科布;
Old Widow Agnes = 老寡妇阿格尼丝 (Agnes = 阿格尼丝); King Edric the Binder = 缚者埃德里克王 (Edric = 埃德里克);
pleiades / the Star God = 星神 (Bagel calls him 主人).
The second layer: Bram Ironhand = 铁手布拉姆; Isolde of the Seven Towers = 七塔的伊索尔德; high mage = 高阶法师; the mages' college = 法师学院;
Carrow = 卡罗; Fennick = 芬尼克; Elin = 艾琳; Tam = 塔姆; Harl = 哈勒; Holt = 霍尔特; dire wolf = 恐狼; grey fever = 灰热病;
Tom Holloway = 汤姆·霍洛韦; the Lantern (Marta's old thieves' name) = 提灯; the bishop's school = 主教学校;
the Thorne arms = 索恩家纹; a thorn branch over a closed gate = 闭门之上的一枝荆棘; signet ring = 印章戒指;
Outer God = 外神; boon = 恩赐; muster = 征召; men-at-arms = 侍卫; adit = 平硐; sapper = 工兵; foundling = 弃婴.
Things: God / the god = 神; the True God = 正神; the old god = 古神; Ullr = 乌勒尔; a god's authority = 权柄;
chosen child = 神选之子; the Ledger of the World = 世界账簿; the Ledger = 账簿; Osric's ledger = 奥斯里克的账本; grace = 神恩;
dream = 梦; sign / wonder = 神迹; prayer = 祈祷; wyrm = 古龙; wyrm-blood = 龙血; the old blood = 古血; wyrmrust = 龙锈;
wyrm-iron = 龙铁; redsilver = 赤银; red brine = 红卤水; the deep door = 深门; the breach = 破口; the Seven Stones = 七石;
the fallen stone = 倒下的那块石头; the seventh stone = 第七块石头; the stone-song / the shepherd's song / Ullr's song = 牧歌; the shepherd-kin = 牧人族;
Old Script = 古文字; moonwort = 月草; white-rooted moonwort = 白根月草; undertaking / common undertaking = 共同行动;
quorum = 足额人数; the blight = 龙锈之害; fox-girl = 狐娘; A Hundred Views of Ashmere = 《灰湖百景》; coin / copper = 铜币;
silver = 银币; reeve = 管事; steward = 总管; foreman = 工头; prioress = 女修院长; herbwife = 草药婆; healer = 医者;
dawn = 黎明; morning = 上午; midday = 正午; afternoon = 下午; dusk = 黄昏; night = 夜晚; day 3 = 第3天.
Dice: check / roll = 检定 / 掷骰; critical = 大成功; success = 成功; partial = 部分成功; failure = 失败; fumble = 大失败; game master = 主持人; character sheet = 角色卡; skills: strength = 力量, craft = 手艺, lore = 学识, song = 歌唱, healing = 医术, hunting = 狩猎, arms = 武艺, magic = 魔法, persuade = 说服, stealth = 潜行, trade = 交易, notice = 察觉.
The song, always exactly:
"Seven stand where one king lay, / sing them still at close of day." = "七石立处君王眠，/ 黄昏一唱石无言。"
"Stone to stone and door to door, / sleep, old blood, beneath the floor." = "石连石兮门对门，/ 古血沉睡地底深。\""""

SYSTEM_ZH = """You translate a report about a simulated medieval valley into Simplified Chinese.

- Write natural, literary Simplified Chinese. Villagers' words stay plain speech, in character; narration may keep an old chronicle's cadence.
- Use the glossary below exactly for names, places, terms and the song.
- Keep markdown markers (#, ##, ###, >, **, *, a leading "- ") and every line break. Keep " / " between lines of verse.
- Use Chinese punctuation, with “ ” and ‘ ’ for quotations.
- Translate everything. Add nothing, explain nothing, keep every number.
- You receive a JSON object mapping ids to English texts. Reply with a JSON object mapping the same ids to their Chinese translations, and nothing else.

GLOSSARY
""" + GLOSSARY_ZH


# ---------------------------------------------------------------------------- data


def _chunks(md: str, heading: str = "## ", limit: int = 3000) -> list[str]:
    """A long document in pieces small enough for one call: at headings, then at paragraphs."""
    out: list[str] = []
    for section in (c.strip() for c in re.split(rf"\n(?={re.escape(heading)})", md or "")):
        piece = ""
        for para in (p.strip() for p in section.split("\n\n")):
            if piece and len(piece) + len(para) > limit:
                out.append(piece)
                piece = ""
            piece = f"{piece}\n\n{para}" if piece else para
        if piece:
            out.append(piece)
    return [c for c in out if c]


def _walk(run: dict, tr) -> None:
    """Replace every shown string in a run with tr(string), in place."""
    shown = displayed_signals(run)
    for sid, s in run["signals"].items():
        s["text"] = tr(s["text"]) if sid in shown else ""
    for a in run["activations"]:
        a["thought"] = tr(a.get("thought") or "")
        a["failures"] = [tr(f) for f in a.get("failures") or []]
    for p in run["proposals"]:
        for k in ("title", "goal", "needs"):
            p[k] = tr(p.get(k) or "")
    for o in run["outcomes"]:
        o["title"], o["public"] = tr(o.get("title") or ""), tr(o.get("public") or "")
        o["might"] = {band: tr(text) for band, text in (o.get("might") or {}).items()}
        _walk_check(o.get("check"), tr)
    for x in run.get("attempts") or []:
        x["what"], x["public"] = tr(x.get("what") or ""), tr(x.get("public") or "")
        x["might"] = {band: tr(text) for band, text in (x.get("might") or {}).items()}
        _walk_check(x.get("check"), tr)
    for c in run.get("checks") or []:
        c["what"] = tr(c.get("what") or "")
        _walk_check(c, tr)
    for g in run.get("god") or []:
        g["thought"] = tr(g.get("thought") or "")
        for x in g.get("acts") or []:
            x["text"] = tr(x.get("text") or "")
        for line in g.get("ledger") or []:
            line["text"], line["witness"] = tr(line["text"]), tr(line.get("witness") or "")
        for line in g.get("struck") or []:
            line["text"] = tr(line["text"])
        for q in g.get("prayers") or []:
            q["text"] = tr(q["text"])
    for q in run.get("prayers") or []:
        q["text"] = tr(q["text"])
    for u in run.get("ullr") or []:
        u["thought"] = tr(u.get("thought") or "")
        for x in u.get("acts") or []:
            x["text"] = tr(x.get("text") or "")
        for q in u.get("prayers") or []:
            q["text"] = tr(q["text"])
    for o in run.get("outer") or []:
        for k in ("thought", "public", "price_text", "dream"):
            o[k] = tr(o.get(k) or "")
        if o.get("refused") != "no boon":  # the page hides this default, so it stays a key, untranslated
            o["refused"] = tr(o.get("refused") or "")
        for q in o.get("prayers") or []:
            q["text"] = tr(q["text"])
    for ag in run["agents"]:
        ag["role"], ag["public"], ag["want"] = tr(ag["role"]), tr(ag["public"]), tr(ag.get("want") or "")
        ag["deeper"] = tr(ag.get("deeper") or "")
        ag["rules"] = [tr(r) for r in ag.get("rules") or []]
        for m in ag["memory"]:
            m["text"] = tr(m["text"])
    run["findings"] = "\n\n".join(tr(c) for c in _chunks(run.get("findings") or "", "### "))
    run["chronicle"] = "\n\n".join(tr(c) for c in _chunks(run.get("chronicle") or ""))


def _walk_check(check: dict | None, tr) -> None:
    for m in (check or {}).get("mods") or []:
        m["why"] = tr(m.get("why") or "")


def _tags(run: dict) -> set[str]:
    tags = {t for ag in run["agents"] for t in ag.get("base") or {}}
    for d in run["days"]:
        for interests in (d.get("interests") or {}).values():
            tags.update(interests)
    return tags


def _localize_run(run: dict, tr) -> dict:
    run = copy.deepcopy(run)
    # The paintbrush reads English: keep what Bagel saw in the words she saw it in.
    for s in run["signals"].values():
        if s["kind"] == "painting":
            s["text_en"] = s["text"]
    for a in run["activations"]:
        if a.get("paintish"):
            seen = " ".join(run["signals"].get(c["signal"], {}).get("text", "") for c in (a.get("contribs") or [])[:2])
            a["sketch_en"] = f"{a.get('thought', '')} {seen}"
    _walk(run, tr)
    for ag in run["agents"]:
        ag["name"], ag["short"] = NAMES_ZH.get(ag["id"], (ag["name"], ag["short"]))
        ag["persona"] = ""
        ag["base"] = {tr(k): v for k, v in (ag.get("base") or {}).items()}
    for d in run["days"]:
        d["interests"] = {aid: {tr(k): v for k, v in i.items()} for aid, i in (d.get("interests") or {}).items()}
    for p in run["places"]:
        p["name"] = PLACES_ZH.get(p["id"], p["name"])
    for o in [*run["outcomes"], *(run.get("attempts") or [])]:
        for e in o.get("applied") or []:
            where = PLACES_ZH.get(str(e.get("place")), "") or NAMES_ZH.get(str(e.get("who")), ("", ""))[1]
            e["label"] = EFFECTS_ZH.get(e.get("type"), e.get("type")) + (f"（{where}）" if where else "")
    for g in run.get("god") or []:
        for line in g.get("struck") or []:
            line["why"] = STRUCK_ZH.get(line.get("why"), line.get("why"))
    return run


def _zh_fix(zh: str) -> str:
    """Names fixed after the first translations were cached: pleiades is 星神, the song is 牧歌."""
    # The spaces around a Latin name in Chinese text go with it.
    return re.sub(r" ?pleiades ?", "星神", zh).replace("石之歌", "牧歌")


def translate_data(data: dict, lang: str, llm: LLM, cache_path: Path, *, workers: int = 8) -> dict:
    """The report data with every shown string translated. Translations are cached by source text."""
    if lang != "zh":
        raise ValueError(f"no translation for language {lang!r}; only 'zh' is supported")
    cache: dict[str, str] = json.loads(cache_path.read_text("utf-8")) if cache_path.exists() else {}
    wanted: set[str] = set()
    for run in data["runs"].values():
        probe = copy.deepcopy(run)
        _walk(probe, lambda s: (wanted.add(s), s)[1] if s and s.strip() else s)
        wanted.update(_tags(run))
    todo = sorted(s for s in wanted if s not in cache)
    print(f"translate: {len(wanted)} strings, {len(todo)} new, ~{sum(map(len, todo)):,} characters", flush=True)
    _translate(todo, cache, llm, cache_path, workers)
    missing = [s for s in todo if s not in cache]
    if missing:
        print(f"translate: {len(missing)} strings left in English after retries", flush=True)
    tr = lambda s: _zh_fix(cache.get(s, s)) if s else s  # noqa: E731
    out = {**data, "lang": lang, "runs": {k: _localize_run(r, tr) for k, r in data["runs"].items()}}
    return out


def _translate(todo: list[str], cache: dict[str, str], llm: LLM, cache_path: Path, workers: int) -> None:
    lock = threading.Lock()
    batches, cur, size = [], [], 0
    for s in todo:
        if cur and (size + len(s) > 4000 or len(cur) >= 30):
            batches.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += len(s)
    if cur:
        batches.append(cur)

    def run(batch: list[str], attempt: int = 0) -> None:
        payload = {str(i): s for i, s in enumerate(batch)}
        try:
            raw = llm.chat([{"role": "system", "content": SYSTEM_ZH}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                           temperature=0.3, max_tokens=8000)
            got = parse_json_object(raw)
        except (ValueError, RuntimeError):
            got = {}
        left = []
        with lock:
            for i, s in enumerate(batch):
                zh = got.get(str(i))
                if isinstance(zh, str) and zh.strip():
                    cache[s] = zh.strip()
                else:
                    left.append(s)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), "utf-8")
        if left and attempt < 2:
            # Retry the stragglers in smaller batches.
            step = max(1, len(left) // 3)
            for j in range(0, len(left), step):
                run(left[j:j + step], attempt + 1)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(run, batches):
            done += 1
            if done % 10 == 0 or done == len(batches):
                print(f"translate: {done}/{len(batches)} batches", flush=True)


# ---------------------------------------------------------------------------- the page's own words

CSS_ZH = """
/* Chinese: CJK faces (the display serif leads, so digits aren't old-style), no faux italics, more leading */
:root { --font-display: "Noto Serif SC", "Songti SC", "SimSun", serif; --font-body: "Alegreya Sans", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif; --font-data: "IBM Plex Mono", "Noto Sans SC", ui-monospace, Consolas, monospace; }
body { line-height: 1.75; }
.thought, .quiet, .view q, .chronicle em, .mem-day p { font-style: normal; }
.eyebrow { letter-spacing: 0.06em; }
h1 { letter-spacing: 0.06em; }
</style>"""

UI_ZH: list[tuple[str, str]] = [
    # head
    ("<title>The Vale of Ashmere</title>", "<title>灰湖谷</title>"),
    ("family=IBM+Plex+Mono:wght@400;500&display=swap", "family=IBM+Plex+Mono:wght@400;500&family=Noto+Serif+SC:wght@400;600&family=Noto+Sans+SC:wght@400;500;700&display=swap"),
    ("</style>", CSS_ZH),
    # static page
    ("An emergence experiment · fifteen language-model villagers · one dawn tick", "一场涌现实验 · 十五位语言模型村民 · 一声黎明的钟"),
    ("<h1>The Vale of Ashmere</h1>", "<h1>灰湖谷</h1>"),
    ("Nothing coordinates these people. Each dawn adds a little energy to everyone and shows the world's omens; cheap physics decides who is stirred enough to act; each villager decides what to do, in character, from their own memory. Everything else that happens here, they did to each other.",
     "没有任何东西协调这些人。每个黎明给每人添一点能量，并显出世界的征兆；廉价的物理规则决定谁被触动到足以行动；每位村民按自己的性格和记忆决定做什么。这里发生的其他一切，都是他们彼此造成的。"),
    ("Nothing coordinates these people except a god who cannot lift a finger. It keeps the Ledger of the World, the one record everyone sees, and can afford a dream or a sign now and then. Each dawn adds a little energy to everyone; cheap physics decides who is stirred enough to act; each villager decides what to do, in character, from their own memory.",
     "除了一位动不了一根手指的神，没有任何东西协调这些人。它掌管世界账簿——人人都看得到的唯一记录——偶尔还能给出一个梦或一个神迹。每个黎明给每人添一点能量；廉价的物理规则决定谁被触动到足以行动；每位村民按自己的性格和记忆决定做什么。"),
    ('aria-label="Choose a run"', 'aria-label="选择一次运行"'),
    (">What emerged<", ">涌现了什么<"),
    ("Read from the logs after the run. None of this was scripted; the world only set the stage.", "运行结束后从日志里读出。这些都不是写好的剧本；世界只是搭好了舞台。"),
    (">The vale, wave by wave<", ">山谷，一波又一波<"),
    ("Scrub through the days. A gilt arc is a stirring caused by another villager's words or deeds; a red mark is something the world showed at dawn. The river reddens as the blight spreads downstream. In the runs with a god, a gilt star is a sign and a gilt crescent marks someone who dreamed; violet marks Bagel's master.",
     "拖动时间轴浏览每一天。金色弧线表示由另一位村民的言行引起的触动；红色标记是世界在黎明时显出的征兆。龙锈向下游蔓延，河水随之变红。在有神的运行里，金色星形是神迹，金色新月标出做了梦的人；紫色属于贝果的主人。"),
    ("Nothing coordinates these people except a god who cannot lift a finger and, through Bagel, an Outer God who can, for a price. Every villager now carries a second layer: a hidden past, a hidden power, and what it would cost to use it. Each dawn adds energy to everyone; cheap physics decides who is stirred enough to act; each villager decides what to do, in character, from their own memory.",
     "除了一位动不了一根手指的神，以及一位借贝果之手、付出代价便能动手的外神，没有任何东西协调这些人。如今每位村民都多了一层背景：隐藏的过去、隐藏的力量，以及动用它的代价。每个黎明给每人添一点能量；廉价的物理规则决定谁被触动到足以行动；每位村民按自己的性格和记忆决定做什么。"),
    ("<h3>A second layer, and an Outer God</h3>", "<h3>第二层背景，与一位外神</h3>"),
    ("In the fourth run every villager carries a second layer: a hidden past, a latent power and what it would cost to use it. Old Bram was a famed adventurer; Mother Isolde a high mage who swore off magic after three disasters; the scribe Tobias is her secret son by Ser Aldric. Fate counts these powers when their owners take part in an undertaking. Bagel's master, pleiades, is an Outer God who sees the vale only through her paintings: when she prays to him, he may grant a boon where she stands, and takes one of her paintings as the price. He cannot touch the binding.",
     "在第四次运行里，每位村民都多了一层背景：隐藏的过去、潜藏的力量，以及动用它的代价。老布拉姆曾是名震一方的冒险者；伊索尔德嬷嬷曾是高阶法师，三次惨祸之后立誓不再施法；抄写员托拜厄斯是她与奥德里克爵士的私生子。这些人参加共同行动时，命运会把他们的本事算进去。贝果的主人星神（pleiades）是一位外神，只能透过她的画看见山谷：她向他祈祷时，他可以在她所站之处降下恩赐，并取走她的一幅画作为代价。他碰不了封印。"),
    ('aria-label="Map of the Vale of Ashmere with villagers\' positions"', 'aria-label="灰湖谷地图与村民的位置"'),
    ('aria-label="Play"', 'aria-label="播放"'),
    ('aria-label="Moment in the run"', 'aria-label="运行中的时刻"'),
    ('<b id="when-label">Day 1 · dawn</b>', '<b id="when-label">第 1 天 · 黎明</b>'),
    (">God's hand<", ">神之手<"),
    ("This run has a god who cannot lift a finger. Each dawn it reads everything, rewrites the Ledger of the World, and may spend grace on a dream or a sign. Every line in the Ledger must cite something a villager said, posted or found; the engine strikes lines whose citations don't check out. Under each act: who it stirred first, and what they did.",
     "这次运行有一位动不了一根手指的神。每个黎明它读遍一切，重写世界账簿，并可以花费神恩给出一个梦或一个神迹。账簿里的每一行都必须引用某位村民说过、贴出或发现的东西；引用对不上的行会被引擎划掉。每一次作为下面都列着：它最先触动了谁，那人又做了什么。"),
    ('<h2 id="h-ripples">Ripples</h2>', '<h2 id="h-ripples">涟漪</h2>'),
    ("A ripple is one chain of cause: a stirring, and every stirring it set off, and every one those set off. Pick one to read how a single dawn turned into a conversation across the vale.",
     "一道涟漪是一条因果链：一次触动，它引发的每一次触动，以及那些触动再引发的。选一道，看一个黎明如何变成一场遍及山谷的对话。"),
    ('<h2 id="h-power">Power</h2>', '<h2 id="h-power">力量</h2>'),
    ("The dawn is the only source of energy. Each stirring spends a unit of a villager's stored reserve, so the vale can never do more than the dawns pay for. When villagers are stirred but spent, they count as “too tired”.",
     "黎明是唯一的能量来源。每次触动都要花掉村民储备中的一个单位，所以山谷做的事永远不会超过黎明所给。村民被触动却已耗尽时，记为“太累”。"),
    ('<h2 id="h-under">Undertakings</h2>', '<h2 id="h-under">共同行动</h2>'),
    ("Anyone can propose a common undertaking at a place; others must come there in person to join or oppose it. At quorum it is attempted at the next dawn, and an impartial fate that knows the hidden truth decides what actually happens.",
     "任何人都可以在某地提议一项共同行动；其他人必须亲自到场才能加入或反对。人数够了，它就在下一个黎明进行，由一位知晓隐藏真相、不偏不倚的命运决定实际发生了什么。"),
    ('<h2 id="h-people">The villagers</h2>', '<h2 id="h-people">村民们</h2>'),
    ("Each has a persona, a few rules they live by, and a private memory file they rewrite every time they act. Open one to read their notes day by day.",
     "每人都有一个人设、几条处世规则，以及一份每次行动都会重写的私人记忆文件。点开任何一位，逐日读他们的笔记。"),
    ('<h2 id="h-bagel">Bagel\'s views</h2>', '<h2 id="h-bagel">贝果的风景</h2>'),
    ("Bagel, the fox-girl painter, came to the vale to paint a hundred views for her master.", "狐娘画师贝果来到山谷，要为她的主人画下百景。"),
    ('<h2 id="h-chron">The chronicle</h2>', '<h2 id="h-chron">编年史</h2>'),
    ("Written afterwards by a chronicler who read the whole record and knows what lay beneath the hill.", "由一位读完全部记录、知道山丘之下埋着什么的编年史家事后写成。"),
    ('<h2 id="h-how">How the vale works</h2>', '<h2 id="h-how">山谷如何运转</h2>'),
    ("<h3>Power</h3>", "<h3>力量</h3>"),
    ("Each dawn adds a fixed amount of energy to every villager's reserve, up to a cap. Acting costs one unit. A quiet stretch lets reserves build; a dramatic morning can then set off a large cascade, like a sandpile.",
     "每个黎明给每位村民的储备添上固定的能量，直到上限。行动花费一个单位。平静的日子让储备积攒起来；之后一个戏剧性的早晨就可能引发一场大崩塌，像沙堆一样。"),
    ("The dawn also shows omens: what the hidden world makes visible at each place, from a red sheen on the millrace to wolves at the fold.",
     "黎明也会显出征兆：隐藏的世界在各处露出的痕迹，从磨坊水道上的一层红光，到羊圈边的狼。"),
    ("<h3>Stirring</h3>", "<h3>触动</h3>"),
    ("Every part of the day, each villager attends to the signals around them: the loudest fully, the next half, and so on. Each signal is weighted by how loud it still is, how much its topics matter to them, whether it names them, and whether it comes from someone they love or resent.",
     "一天中的每个时段，每位村民都会留意身边的信号：最响的全部注意，其次的注意一半，依此类推。每个信号的分量取决于它此刻还有多响、它的话题对他们多重要、是否点了他们的名，以及是否出自他们所爱或所恨的人。"),
    ("They stir with probability S² / (S² + θ²). A signal they already acted on counts for less each time.", "他们以概率 S² / (S² + θ²) 被触动。已经回应过的信号，每多回应一次，分量就更轻一些。"),
    ("<h3>Word travels</h3>", "<h3>消息流传</h3>"),
    ("Speech is heard only where it is spoken. Strong signals travel one road per part of the day as rumour, weaker with each hop. Worked-up speakers are louder, so alarm travels and idle talk stays home. Notices and paintings stay where they hang for days.",
     "话只在说出的地方被听见。强信号每个时段沿一条路以传言的方式传出去，每传一站就弱一分。激动的人说话更响，所以警报传得开，闲话留在原地。告示和画挂在原处，能留好几天。"),
    ("<h3>A god, in one run</h3>", "<h3>一位神（只在一次运行中）</h3>"),
    ("One run adds a god. Each dawn it reads the hidden truth, every villager's notes, the day's words and deeds, and their prayers. It keeps the Ledger of the World, the one record every villager sees whenever they act; each line must cite something a villager said, posted or found, or that the world showed them. It gains one grace a dawn, saving up to three, to spend on a dream for one villager or a sign at one place. It cannot move a stone.",
     "有一次运行加入了一位神。每个黎明它读取隐藏的真相、每位村民的笔记、当天的言行，以及他们的祈祷。它掌管世界账簿——每位村民行动时都看得到的唯一记录；每一行都必须引用某位村民说过、贴出或发现的东西，或世界向他们显出的东西。它每个黎明得到一点神恩，最多攒三点，可以给一位村民一个梦，或在一处显一个神迹。它挪不动一块石头。"),
    ("<h3>The minds</h3>", "<h3>心智</h3>"),
    ("Only a stirred villager calls the language model, with their persona, the world's rules, what stirred them and their own memory file. They answer with up to three actions and a rewritten memory. Topics they act on sharpen their attention; unused ones drift back.",
     "只有被触动的村民才会调用语言模型，带着他们的人设、世界规则、触动他们的东西和他们自己的记忆文件。他们最多回应三个行动，并重写记忆。回应过的话题会让他们更敏锐；用不上的则慢慢回落。"),
    # script: setup
    ("const ALL = JSON.parse(document.getElementById('vale-data').textContent);",
     "const ALL = JSON.parse(document.getElementById('vale-data').textContent);\n  document.documentElement.lang = 'zh-CN';"),
    ("const WAVES = ['dawn', 'morning', 'midday', 'afternoon', 'dusk', 'night'];", "const WAVES = ['黎明', '上午', '正午', '下午', '黄昏', '夜晚'];"),
    ("const GODK = { dream: 'a dream', sign: 'a sign', ledger: 'the Ledger' };", "const GODK = { dream: '一个梦', sign: '一个神迹', ledger: '账簿' };"),
    ("const OUTERK = { dream: 'a dream from pleiades', boon: \"pleiades' boon\" };", "const OUTERK = { dream: '星神的一个梦', boon: '星神的恩赐' };"),
    ("'boons from pleiades'", "'星神的恩赐'"),
    ("'stirrings moved by pleiades'", "'由星神触动的次数'"),
    ("`A boon from pleiades: ${od.public}`", "`星神的恩赐：${od.public}`"),
    ("`${a.name} heard her master in a dream`", "`${a.name} 在梦里听见了主人`"),
    ("`A boon at ${R.placesById[od.boon.place]?.name || ''}: `", "`${R.placesById[od.boon.place]?.name || ''}的恩赐：`"),
    ("`paid with Bagel's painting: “${od.price_text}”`", "`以贝果的一幅画为代价：“${od.price_text}”`"),
    ("'A dream for Bagel: '", "'给贝果的梦：'"),
    ("'At dawn · pleiades, through Bagel'", "'黎明 · 星神，借贝果之手'"),
    ("`pleiades · a boon at ${R.placesById[od.boon.place]?.name || ''}`", "`星神 · ${R.placesById[od.boon.place]?.name || ''}的恩赐`"),
    ("'pleiades · no boon'", "'星神 · 没有恩赐'"),
    ("'In her dream: '", "'在她的梦里：'"),
    ("'Boons from pleiades'", "'星神的恩赐'"),
    ("'What no one in the vale knows'", "'山谷里没人知道的事'"),
    ('const ULLRK = { dream: \'a dream from old Ullr\', sign: "old Ullr\'s sign" };', "const ULLRK = { dream: '古神乌勒尔的一个梦', sign: '古神乌勒尔的神迹' };"),
    ("'nights old Ullr was awake'", "'乌勒尔醒着的夜数'"),
    ("'stirrings moved by old Ullr'", "'由乌勒尔触动的次数'"),
    ('Nothing coordinates these people except three gods: the True God, who keeps the Ledger but cannot lift a finger; the Star God, who works small miracles through Bagel for a price; and old Ullr, who wakes only while his song is sung. Every villager carries a second layer: a hidden past, a hidden power, and what it would cost to use it. Each dawn adds energy to everyone; cheap physics decides who is stirred enough to act; each villager decides what to do, in character, from their own memory.', '除了三位神，没有任何东西协调这些人：正神掌管世界账簿，却动不了一根手指；星神借贝果之手、付出代价施行小小的奇迹；古神乌勒尔只在牧歌唱响时醒来。每位村民都有第二层背景：隐藏的过去、隐藏的力量，以及动用它的代价。每个黎明给每人添一点能量；廉价的物理规则决定谁被触动到足以行动；每位村民按自己的性格和记忆决定做什么。'),
    ('`Old Ullr: ${x.text}`', '`古神乌勒尔：${x.text}`'),
    ('`${a.name} dreamed of old Ullr`', '`${a.name} 梦见了古神乌勒尔`'),
    ("'At dawn · old Ullr'", "'黎明 · 古神乌勒尔'"),
    ("'The hunt: '", "'狩猎：'"),
    ("el('i', { text: 'Gilt' }), ': the True God.',", "el('i', { text: '金色' }), '：正神。',"),
    ("el('i', { text: 'Violet' }), ': the Star God, through Bagel.']", "el('i', { text: '紫色' }), '：星神，借贝果之手。']"),
    ("el('i', { text: 'Teal' }), ': old Ullr, while his song holds him awake.']", "el('i', { text: '青色' }), '：古神乌勒尔，在牧歌让他醒着的时候。']"),
    ('`old Ullr · awake, ${ud.awake} more nights`', '`古神乌勒尔 · 醒着，还剩 ${ud.awake} 夜`'),
    ("'old Ullr · stirring in his sleep'", "'古神乌勒尔 · 在睡梦中翻身'"),
    ("'He did nothing.'", "'他什么也没做。'"),
    ("'Nights old Ullr was awake'", "'乌勒尔醒着的夜数'"),
    ('<h3>Ullr awake, and danger instead of vetoes, from the sixth run</h3>', '<h3>醒着的乌勒尔，以及以风险代替否决（自第六次运行起）</h3>'),
    ("From the sixth run old Ullr acts in his own right while his song holds him awake: each dawn a dream, a sign on his high places, or, once, the hunt that turns the wolves. The True God sees his signs but not the dreams he sends his chosen. Precautions become a risk rather than a veto: an undertaking goes ahead with whoever came, and people can be hurt. The Star God has no plan for the vale; he wakes for his follower's prayers and for her harm.", '从第六次运行起，古神乌勒尔在牧歌让他醒着的时候亲自行事：每个黎明托一个梦，或在他的高地显一个神迹，或者——仅此一次——发动狩猎，把狼群赶走。正神看得见他的神迹，却看不见他托给神选之子的梦。防范措施从一票否决变成了风险：共同行动带着到场的人照常进行，有人可能受伤。星神对山谷别无图谋；他只为信徒的祈祷和她的安危而醒来。'),
    ("`to be done at ${R.placesById[p.site]?.name || p.site}, at ${WAVES[p.when || 0]}`", "`在${R.placesById[p.site]?.name || p.site}进行，时在${WAVES[p.when || 0]}`"),
    ("` · old Ullr wakes (${h.ullr_awake} nights)`", "` · 古神乌勒尔苏醒（还剩 ${h.ullr_awake} 夜）`"),
    ("<h3>Three gods, from the fifth run</h3>", "<h3>三位神（自第五次运行起）</h3>"),
    ("The vale worships the True God at Saint Wenna's chapel; it loves the people, does not want the old god to wake, and is wary of the Outer God. The Seven Stones belong to Ullr, the old god of the hills: as faith turned away from him his power waned, and that is why the binding loosened. The shepherd's song, sung at dusk with both verses among seven standing stones, wakes his authority for a few nights, and the blood sleeps while it lasts. Bagel's master, pleiades, the Star God, wields the power of the stars, but his miracles only ease what they touch. Undertakings can now be set for an hour and a place, and those within a road of it come.",
     "山谷在圣文娜礼拜堂敬拜正神；正神爱世人，却不愿古神苏醒，也提防外神。七石属于山岭的古神乌勒尔：信仰离他而去，他的力量随之式微，封印因此松动。黄昏时在七块立起的石头之间唱完两段牧歌，能唤醒他的权柄几夜，权柄醒着时龙血便沉睡。贝果的主人星神能动用群星之力，但他的奇迹只能消解所触之处的表象。从这一次起，共同行动可以约定时辰与地点，一条路以内的人都会赶来。"),
    ("const OUTCOME = { success: 'success', partial: 'partial', failure: 'failure', due: 'due', open: 'open', critical: 'critical', fumble: 'fumble', unattempted: 'nobody came' };",
     "const OUTCOME = { success: '成功', partial: '部分成功', failure: '失败', due: '待尝试', open: '征集中', critical: '大成功', fumble: '大失败', unattempted: '无人到场' };"),
    # header
    ("`${run.physics.refill} energy per dawn${(run.god || []).length ? ' · a god' : ''}`", "`每个黎明 ${run.physics.refill} 能量${(run.god || []).length ? ' · 有神' : ''}`"),
    ("[R.maxDay, 'days']", "[R.maxDay, '天']"),
    ("[s.activations || 0, 'stirrings']", "[s.activations || 0, '次触动']"),
    ("'stirred but too tired'", "'被触动但太累'"),
    ("[s.ripples || 0, 'ripples']", "[s.ripples || 0, '道涟漪']"),
    ("'largest ripple'", "'最大涟漪'"),
    ("'branching ratio'", "'分支比'"),
    ("'undertakings proposed / attempted'", "'共同行动 提议 / 尝试'"),
    ("'dreams / signs'", "'梦 / 神迹'"),
    ("'Ledger lines written'", "'写过的账簿行'"),
    ("'stirrings moved by the god'", "'由神触动的次数'"),
    # map
    ("'the Hollowbrook'", "'空溪'"),
    ("`A sign: ${x.text}`", "`神迹：${x.text}`"),
    ("`${a.name}, open notes`", "`${a.name}，打开笔记`"),
    ("`${a.name} dreamed last night`", "`${a.name} 昨夜做了梦`"),
    # moment panel
    ("const to = s.to ? (R.agentsById[s.to]?.short || s.to) : 'everyone';", "const to = s.to ? (R.agentsById[s.to]?.short || s.to) : '众人';"),
    ("`to ${to}: “${s.text}”`", "`对${to}说：“${s.text}”`"),
    ("`posted: “${s.text}”`", "`贴出：“${s.text}”`"),
    ("`painted: ${s.text}`", "`画了：${s.text}`"),
    ("`proposed “${(s.text.split(':')[0] || '').trim()}”: ${s.text.split(':').slice(1).join(':').trim()}`", "`提议：${s.text}`"),
    ("`prayed: “${q.text}”`", "`祈祷：“${q.text}”`"),
    ("`Day ${day} · ${WAVES[wave]}`", "`第 ${day} 天 · ${WAVES[wave]}`"),
    ("`Attempted at ${WAVES[o.wave || 0]} · ${OUTCOME[o.outcome] || o.outcome}`", "`${WAVES[o.wave || 0]}时尝试 · ${OUTCOME[o.outcome] || o.outcome}`"),
    ("`${R.placesById[o.loc]?.name || ''} · the world shows`", "`${R.placesById[o.loc]?.name || ''} · 世界显示`"),
    ("`A dream for ${R.agentsById[x.to]?.short || x.to}: `", "`给${R.agentsById[x.to]?.short || x.to}的梦：`"),
    ("`A sign at ${R.placesById[x.at]?.name || x.at}: `", "`${R.placesById[x.at]?.name || x.at}的神迹：`"),
    ("'Written in the Ledger by an unseen hand: '", "'一只看不见的手写进账簿：'"),
    ("'New in the Ledger: '", "'账簿新增：'"),
    ("` (${l.witness})`", "`（${l.witness}）`"),
    ("'At dawn · the god'", "'黎明 · 神'"),
    ("`stirred by ${via}, carrying ${R.agentsById[parent.agent].short}'s words`", "`被${via}触动，传递着${R.agentsById[parent.agent].short}的话`"),
    ("`stirred by ${via}`", "`被${via}触动`"),
    ("`stirred by ${R.agentsById[parent.agent].short}`", "`被${R.agentsById[parent.agent].short}触动`"),
    ("'stirred by the world'", "'被世界触动'"),
    ("`at ${R.placesById[a.place]?.name || 'the road'}`", "`在${R.placesById[a.place]?.name || '路上'}`"),
    ("'Stirred, but did nothing.'", "'被触动了，却什么也没做。'"),
    ("'Quiet. Nobody was stirred enough to act.'", "'安静。没有人被触动到足以行动。'"),
    ("h.shaft_open ? 'the deep door is open' : 'the deep door is shut'", "h.shaft_open ? '深门敞开' : '深门已关'"),
    ("`${sealed} · water worst at ${R.placesById[worst[0]]?.name} (${Math.round(worst[1] * 100)}%)`", "`${sealed} · 水最糟在${R.placesById[worst[0]]?.name}（${Math.round(worst[1] * 100)}%）`"),
    ("setAttribute('aria-label', 'Play')", "setAttribute('aria-label', '播放')"),
    ("setAttribute('aria-label', 'Pause')", "setAttribute('aria-label', '暂停')"),
    # ripples
    ("stirrings · ${r.agents.length} people · ${r.places.length} places · depth ${r.depth}", "次触动 · ${r.agents.length} 人 · ${r.places.length} 地 · 深 ${r.depth}"),
    ("` · days ${r.days[0]}–${r.days[r.days.length - 1]}`", "` · 第 ${r.days[0]}–${r.days[r.days.length - 1]} 天`"),
    ("` · day ${r.day}`", "` · 第 ${r.day} 天`"),
    ("`${R.agentsById[a.agent].short}, day ${a.day}: ", "`${R.agentsById[a.agent].short}，第 ${a.day} 天："),
    ("'No ripple has more than one stirring yet.'", "'还没有超过一次触动的涟漪。'"),
    ("`It began with a dream sent to ${R.agentsById[trigger.to]?.short || ''}`", "`起于送给${R.agentsById[trigger.to]?.short || ''}的一个梦`"),
    ("`It began with a sign at ${R.placesById[trigger.loc]?.name || ''}`", "`起于${R.placesById[trigger.loc]?.name || ''}的一个神迹`"),
    ("'It began with a line in the Ledger'", "'起于账簿里的一行'"),
    ("'It began with'", "'起因'"),
    ("`day ${a.day} · ${WAVES[a.wave]} · ${R.placesById[a.place]?.name || ''}`", "`第 ${a.day} 天 · ${WAVES[a.wave]} · ${R.placesById[a.place]?.name || ''}`"),
    ("' stirred, did nothing'", "' 被触动，什么也没做'"),
    # power
    ("'Stirrings each day'", "'每天的触动'"),
    ("{ name: 'acted',", "{ name: '行动了',"),
    ("`Each dawn adds ${R.physics.refill} to each of ${R.agents.length} reserves: ${(R.physics.refill * R.agents.length).toFixed(1)} units of energy a day.`",
     "`每个黎明给 ${R.agents.length} 份储备各添 ${R.physics.refill}：每天共 ${(R.physics.refill * R.agents.length).toFixed(1)} 单位能量。`"),
    ("'How big ripples get'", "'涟漪能有多大'"),
    ("'ripples of this many stirrings'", "'含这么多次触动的涟漪'"),
    ("'Most stirrings end where they start; a few run on through many people and places.'", "'大多数触动在起点就结束；少数会穿过许多人和许多地方。'"),
    ("'Blight in the water'", "'水中的龙锈'"),
    ("title: 'Sickness'", "title: '疾病'"),
    ("'Energy per villager per dawn'", "'每位村民每个黎明的能量'"),
    ("'Days run'", "'运行天数'"),
    ("['Stirrings', (r)", "['触动次数', (r)"),
    ("'Stirrings per day'", "'每天触动'"),
    ("'Stirred but too tired'", "'被触动但太累'"),
    ("'Branching ratio'", "'分支比'"),
    ("'Largest ripple'", "'最大涟漪'"),
    ("'Deepest chain'", "'最深的链'"),
    ("'Ripples crossing places'", "'跨地点的涟漪'"),
    ("'Ripples spanning days'", "'跨天的涟漪'"),
    ("'Undertakings proposed'", "'提议的共同行动'"),
    ("'Undertakings attempted'", "'尝试的共同行动'"),
    ("['Succeeded', (r)", "['成功', (r)"),
    ("'Deep door shut at the end'", "'结束时深门已关'"),
    ("'Stones sung with both verses'", "'七石唱过两段'"),
    ("'Ashmere water at the end'", "'结束时灰湖的水'"),
    ("['A god', (r)", "['有神', (r)"),
    ("'Dreams / signs'", "'梦 / 神迹'"),
    ("'yes' : 'no'", "'是' : '否'"),
    ("'The same physics with dice instead of minds'", "'同样的物理规则，用骰子代替心智'"),
    ("`${ALL.sweepDays} days per row, villagers replaced by random speakers. Power sets the volume; with no dawn power the vale falls silent once its first reserves are spent.`",
     "`每行 ${ALL.sweepDays} 天，村民换成随机说话者。力量决定音量；没有黎明的能量，最初的储备一耗尽，山谷便归于沉寂。`"),
    ("['Energy / dawn', 'Threshold ×', 'Stirrings / day', 'Too tired', 'Branching', '最大涟漪', '最深的链']", "['能量 / 黎明', '阈值 ×', '触动 / 天', '太累', '分支比', '最大涟漪', '最深的链']"),
    ("'The runs, side by side'", "'各次运行并排比较'"),
    # the god
    ("'It stirred nobody first.'", "'它没有最先触动任何人。'"),
    ("'Stirred first: '", "'最先触动：'"),
    ("[i ? '; ' : '', who(a.agent), ` (${WAVES[a.wave]}${first ? `: ${clip(first.text, 110)}` : ''})`]",
     "[i ? '；' : '', who(a.agent), `（${WAVES[a.wave]}${first ? `：${clip(first.text, 110)}` : ''}）`]"),
    ("`A dream for ${R.agentsById[x.to]?.name || x.to}`", "`给${R.agentsById[x.to]?.name || x.to}的梦`"),
    ("`A sign at ${R.placesById[x.at]?.name || x.at}${x.seen_by && x.seen_by.length ? '' : ' · nobody there'}`", "`${R.placesById[x.at]?.name || x.at}的神迹${x.seen_by && x.seen_by.length ? '' : ' · 无人在场'}`"),
    ("'Written in the Ledger'", "'写进账簿'"),
    ("' · by a human hand'", "' · 出自人手'"),
    ("`answering ${R.agentsById[answered.agent]?.short}'s prayer: “${answered.text}”`", "`回应${R.agentsById[answered.agent]?.short}的祈祷：“${answered.text}”`"),
    ("` at ${R.placesById[q.place]?.name || ''}, ${WAVES[q.wave]} of day ${q.day}: “${q.text}”`", "` 在${R.placesById[q.place]?.name || ''}，第 ${q.day} 天${WAVES[q.wave]}：“${q.text}”`"),
    ("`${l.witness} · new, moved ${movedBy(l.signal).length} first`", "`${l.witness} · 新增，最先触动 ${movedBy(l.signal).length} 人`"),
    ("`struck: ${l.why}`", "`已划掉：${l.why}`"),
    ("`Day ${g.day}`", "`第 ${g.day} 天`"),
    ("`grace ${g.grace_before} → ${g.grace}`", "`神恩 ${g.grace_before} → ${g.grace}`"),
    ("'No dream, no sign: the god kept its grace.'", "'无梦，无神迹：神留着它的神恩。'"),
    ("'Prayers it heard'", "'它听到的祈祷'"),
    ("`The Ledger that morning · ${(g.ledger || []).length} lines, ${fresh.length} new`", "`那天早晨的账簿 · ${(g.ledger || []).length} 行，新增 ${fresh.length} 行`"),
    # undertakings
    ("'Nobody has proposed a common undertaking yet.'", "'还没有人提议共同行动。'"),
    ("`day ${p.day} · ${R.placesById[p.place]?.name} · needs ${p.quorum}`", "`第 ${p.day} 天 · ${R.placesById[p.place]?.name} · 需 ${p.quorum} 人`"),
    ("`Needs: ${p.needs}`", "`所需：${p.needs}`"),
    ("'Joined: '", "'加入：'"),
    ("'Opposed: '", "'反对：'"),
    ("'Changed the world: '", "'改变了世界：'"),
    # villagers
    ("`${counts[a.id] || 0} stirrings · spoke to ${(spokeTo[a.id] || new Set()).size} · sought by ${(namedBy[a.id] || new Set()).size}`",
     "`${counts[a.id] || 0} 次触动 · 对 ${(spokeTo[a.id] || new Set()).size} 人说过话 · 被 ${(namedBy[a.id] || new Set()).size} 人找过`"),
    ("m.day ? `day ${m.day}` : 'before'", "m.day ? `第 ${m.day} 天` : '之前'"),
    ("text: 'Close'", "text: '关闭'"),
    ("'What they want'", "'他们想要什么'"),
    ("'Rules they live by'", "'他们的处世规则'"),
    ("'Spoke directly to'", "'直接交谈过'"),
    ("'What they pay attention to (bar: now, tick: at the start)'", "'他们关注什么（条：现在，刻度：开始时）'"),
    ("'Their memory file, as they rewrote it (new words highlighted)'", "'他们的记忆文件，按他们重写的样子（新词高亮）'"),
    # Bagel
    ("'Bagel came to the vale to paint a hundred views for her master. Her paintings hang where she paints them, and anyone passing sees them. Each is rendered here from her own description, followed by the views she set aside.'",
     "'贝果来到山谷，要为她的主人画下百景。她的画挂在她作画的地方，路过的人都看得见。这里每一幅都照她自己的描述绘出，后面是她搁下没画的风景。'"),
    ("'Bagel came to the vale to paint a hundred views for her master. Once the water turned red, she stopped painting. These are the views she set aside, in her own words, sketched from what she was looking at, beside what she did instead.'",
     "'贝果来到山谷，要为她的主人画下百景。水一变红，她就停了笔。这些是她搁下的风景：用她自己的话，照着她当时所见草草勾出，旁边是她转而去做的事。'"),
    ("`Day ${Math.floor(s.born)} · ${R.placesById[s.loc]?.name || ''}`", "`第 ${Math.floor(s.born)} 天 · ${R.placesById[s.loc]?.name || ''}`"),
    ("`A faint sketch of what Bagel saw on day ${a.day}`", "`贝果在第 ${a.day} 天所见的淡淡素描`"),
    ("`Day ${a.day} · ${WAVES[a.wave]} · ${R.placesById[a.place]?.name || ''}`", "`第 ${a.day} 天 · ${WAVES[a.wave]} · ${R.placesById[a.place]?.name || ''}`"),
    ("text: 'Instead'", "text: '转而'"),
    ("`Her notes: ${mem.length ? mem[mem.length - 1].text : ''}`", "`她的笔记：${mem.length ? mem[mem.length - 1].text : ''}`"),
    # the dice, from the seventh run
    ('<h2 id="h-dice">The dice</h2>', '<h2 id="h-dice">骰子</h2>'),
    ("Nothing hard is certain. Whoever tries something rolls a d100 under a skill from their character sheet, plus whatever helps and minus whatever hinders. Fate, as game master, sets the check and writes every outcome before the die falls; the roll picks one. Each bar is the whole die: green succeeds, gilt half succeeds, grey fails, red goes wrong. The black tick is where the die fell.",
     "没有十拿九稳的难事。谁要尝试什么，就用角色卡上的一项技能掷一次 d100，有利的加上，不利的减去。命运作为主持人设定检定，并在骰子落下之前写好每一种结局；掷出的点数挑中其中一种。每一条横条就是整颗骰子：绿色成功，金色部分成功，灰色失败，红色出事。黑色刻度是骰子落下的位置。"),
    ('aria-label="Which rolls"', 'aria-label="哪些检定"'),
    ("<h3>Dice, and a month, from the seventh run</h3>", "<h3>骰子，与一个月（自第七次运行起）</h3>"),
    ("Every villager has a character sheet: twelve skills out of 100, with the second layer written into the numbers (Brannoc's craft 80, Mother Isolde's magic 85, Wynn's song 75). Anyone can attempt anything where they stand, and an undertaking no longer waits for a quorum: it is tried at its hour with whoever came, even one. Fate, as game master, picks the skill and who rolls it, gives each modifier a reason, sets how wild the attempt is, and writes all five outcomes before the roll. The engine rolls a d100: at or under a fifth of the target is a critical, at or under the target a success, up to twenty over a partial; a roll in the fumble range goes wrong whatever the odds. Tending the sick and walking while fevered roll too. The seventh run lasts a month.",
     "每位村民都有一张角色卡：十二项技能，满分 100，第二层背景就写在数字里（布兰诺克的手艺 80，伊索尔德嬷嬷的魔法 85，温的歌唱 75）。任何人都可以在所站之处尝试任何事；共同行动也不再等人数凑齐：到了约定的时辰，带着到场的人照常进行，哪怕只有一人。命运作为主持人，选定靠哪项技能、由谁来掷，为每一项修正写明理由，定下这次尝试有多凶险，并在掷骰之前写好全部五种结局。引擎掷一次 d100：不超过目标值五分之一为大成功，不超过目标值为成功，超出二十以内为部分成功；落进大失败区间，不论胜算多高都会出事。照料病人和带病赶路也要掷骰。第七次运行持续一个月。"),
    ('dice: "Nothing coordinates these people except three gods and the dice. The True God keeps the Ledger but cannot lift a finger; the Star God works small miracles through Bagel for a price; old Ullr wakes only while his song is sung. Every villager carries a second layer and a character sheet, and whatever anyone tries, alone or together, comes to something: the dice say what. Each dawn adds energy to everyone; cheap physics decides who is stirred enough to act; each villager decides what to do, in character, from their own memory.",',
     'dice: "除了三位神和骰子，没有任何东西协调这些人。正神掌管世界账簿，却动不了一根手指；星神借贝果之手、付出代价施行小小的奇迹；古神乌勒尔只在牧歌唱响时醒来。每位村民都有第二层背景和一张角色卡；无论独自还是一同尝试什么，总会有个结果——由骰子说了算。每个黎明给每人添一点能量；廉价的物理规则决定谁被触动到足以行动；每位村民按自己的性格和记忆决定做什么。",'),
    ("'dice rolled'", "'次掷骰'"),
    ("'successes / fumbles'", "'成功 / 大失败'"),
    ("`${R.agentsById[c.roller]?.short || ''}: ${c.what} · ${OUTCOME[c.band]}`", "`${R.agentsById[c.roller]?.short || ''}：${c.what} · ${OUTCOME[c.band]}`"),
    ("const SKILL = { strength: 'strength', craft: 'craft', lore: 'lore', song: 'song', healing: 'healing', hunting: 'hunting', arms: 'arms', magic: 'magic', persuade: 'persuade', stealth: 'stealth', trade: 'trade', notice: 'notice' };",
     "const SKILL = { strength: '力量', craft: '手艺', lore: '学识', song: '歌唱', healing: '医术', hunting: '狩猎', arms: '武艺', magic: '魔法', persuade: '说服', stealth: '潜行', trade: '交易', notice: '察觉' };"),
    ("const CHECKK = { undertaking: 'an undertaking', attempt: 'tried alone', tend: 'tending the sick', travel: 'a fevered walk' };",
     "const CHECKK = { undertaking: '共同行动', attempt: '独自尝试', tend: '照料病人', travel: '带病赶路' };"),
    ("`rolled ${c.roll} against ${c.target}: ${OUTCOME[c.band]}`", "`目标 ${c.target}，掷出 ${c.roll}：${OUTCOME[c.band]}`"),
    ("` · fumbles on ${c.fumble}+` : ''} · rolled `", "` · ${c.fumble} 及以上大失败` : ''} · 掷出 `"),
    ("'If the die had fallen otherwise'", "'如果骰子落得不同'"),
    ("'How the die fell'", "'骰子怎么落'"),
    ("`${n} rolls: ${kinds.map((k) => `${R.checks.filter((c) => c.kind === k).length} ${CHECKK[k]}`).join(', ')}. The average roll was ${mean.toFixed(1)}; a fair die averages 50.5.`",
     "`共掷骰 ${n} 次：${kinds.map((k) => `${CHECKK[k]} ${R.checks.filter((c) => c.kind === k).length} 次`).join('，')}。平均点数 ${mean.toFixed(1)}；一颗公平的骰子平均是 50.5。`"),
    ("'Rolls each day'", "'每天的掷骰'"),
    ("{ name: 'succeeded',", "{ name: '成功',"),
    ("{ name: 'partly',", "{ name: '部分成功',"),
    ("{ name: 'failed or went wrong',", "{ name: '失败或出事',"),
    ("'every roll'", "'全部检定'"),
    ("`Day ${c.day}`", "`第 ${c.day} 天`"),
    ("`with ${out.present.filter((x) => x !== c.roller).map((x) => R.agentsById[x]?.short || x).join(', ')}`",
     "`同行：${out.present.filter((x) => x !== c.roller).map((x) => R.agentsById[x]?.short || x).join('、')}`"),
    ("dice: 'From the seventh run an undertaking needs no quorum: it is attempted at its place and hour with whoever comes, even one. Fate, as game master, sets a d100 check on the best skill among those who came, adds what helps and subtracts what hinders, and writes every outcome before the die falls; the roll picks one.',",
     "dice: '从第七次运行起，共同行动不再需要凑够人数：到了约定的地点和时辰，带着到场的人照常进行，哪怕只有一人。命运作为主持人，用到场者中最合适的那项技能设一次 d100 检定，加上有利的、减去不利的，并在骰子落下之前写好每一种结局；掷出的点数挑中其中一种。',"),
    ("`day ${p.day} · posted at ${R.placesById[p.place]?.name}`", "`第 ${p.day} 天 · 贴于${R.placesById[p.place]?.name}`"),
    ("'Came: '", "'到场：'"),
    ("`attempted together with: ${together.join('; ')}`", "`与之一同尝试：${together.join('；')}`"),
    ("'Tried alone'", "'独自尝试'"),
    ("'Dice rolled'", "'掷骰次数'"),
    ("'Fumbles'", "'大失败'"),
    ("<h3>Dice only when it matters, from the eighth run</h3>", "<h3>只在要紧时掷骰（自第八次运行起）</h3>"),
    ("The seventh run rolled for everything, and about two thirds of its rolls were for routine care, whose fumbles slowly wore the sick down. From the eighth run the game master first decides whether to roll at all: work a capable person simply does, such as keeping watch, sitting with the sick or carrying a manageable load, gets done without dice. A fumble falls on those doing the work and what they risk, not on those they care for. Goods the vale hands out are its plain goods, so they can be passed on, and someone who tries something may still set off afterwards.",
     "第七次运行事事掷骰，其中约三分之二是日常照料，这些检定的大失败一点点拖垮了病人。从第八次运行起，主持人先判断要不要掷骰：守夜、陪护病人、搬运力所能及的东西，这类能干的人照常就能做成的事，不必掷骰，直接做成。大失败只落在动手做事的人和他们押上的东西上，不落在被照料的人身上。山谷给出的物品都是普通货物，可以转手；尝试过某件事的人，之后也照样可以动身。"),
    (": 'done' })", ": '做成' })"),
    ("'no roll needed: routine work simply gets done'", "'无需掷骰：日常的事照常做成'"),
    ("`${unrolled} more things were simply done, with no roll needed.`", "`另有 ${unrolled} 件事无需掷骰，照常做成。`"),
    # chronicle and footer
    ("'The chronicler writes once a run is finished.'", "'编年史家会在一次运行结束后执笔。'"),
    ("`Run “${R.meta.run}” · ${R.maxDay} days · physics: refill ${R.physics.refill}, reserve cap ${R.physics.reserve_cap}, threshold × ${R.physics.theta_scale}. Model: ${ALL.model}.`",
     "`运行“${R.meta.run}” · ${R.maxDay} 天 · 物理参数：每日补充 ${R.physics.refill}，储备上限 ${R.physics.reserve_cap}，阈值 × ${R.physics.theta_scale}。模型：${ALL.model}。`"),
]


def localize(html: str, lang: str) -> str:
    """The template's own words in another language. Fails if any source string is missing."""
    if lang != "zh":
        raise ValueError(f"no page translation for language {lang!r}; only 'zh' is supported")
    missing = []
    for old, new in UI_ZH:
        if old not in html:
            missing.append(old)
            continue
        html = html.replace(old, new)
    if missing:
        raise ValueError("the template no longer contains these strings; update vale/i18n.py:\n" + "\n".join(f"  {m[:110]}" for m in missing))
    return html

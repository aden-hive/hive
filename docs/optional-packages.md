# Optional packages

Some features live in packages you install next to Hive rather than in Hive itself: a
**channel** connects a chat app to a queen, and a **turn-context** package shows a queen
something before each of her turns. Hive finds an installed package when `hive open` or
`hive serve` starts, and runs it only when `configuration.json` turns it on.

Installing one takes three steps: install it into the Python environment Hive runs from, turn it
on, and restart Hive.

## 1. Install it where Hive runs

The package has to be in the same Python environment as Hive. Which environment that is depends
on how you installed Hive:

| You installed Hive with | Install a package with |
|---|---|
| The quickstart (a clone of this repository) | From the repository's folder: `uv pip install <package>`. This puts it in the repository's `.venv`. Running the quickstart again, or `uv sync`, removes packages that aren't part of Hive, so install it again afterwards. |
| `pip install "aden-hive[tools]"` | `pip install <package>`, with the same `pip` (the same virtual environment active). |
| `uv tool install "aden-hive[tools]"` | `uv tool install "aden-hive[tools]" --with <package>`. This reinstalls the tool with the package. |
| `pipx install "aden-hive[tools]"` | `pipx inject aden-hive <package>` |

`<package>` can be any of these:

- A name on PyPI: `some-package`
- A downloaded wheel: `./some_package-0.1.0-py3-none-any.whl`
- A Git URL at a tag: `"some-package @ git+https://github.com/owner/some-package@v0.1.0"`. For a
  private repository, use one you can reach, for example
  `git+ssh://git@github.com/owner/some-package.git@v0.1.0`.

A package names the Hive version it needs, and the installer refuses it when your Hive is older:
update Hive first.

## 2. Turn it on

Add the package's section to `~/.hive/configuration.json` (or `$HIVE_HOME/configuration.json`),
with `"enabled": true` and the settings its README lists:

```json
{
  "channels": {"<channel name>": {"enabled": true}},
  "turn_context": {"<package name>": {"enabled": true}}
}
```

A channel goes under `channels`, a turn-context package under `turn_context`. The name is the one
the package's README gives.

## 3. Restart Hive and check

Restart `hive open` or `hive serve`. For each installed package, the server log says one of these:

| Log line | Meaning |
|---|---|
| `channel '<name>' started`, `turn context '<name>' started` | Running. |
| `... is installed but off: set ... enabled in configuration.json` | Installed, not turned on: check step 2. |
| `... failed to start`, followed by the error | Installed and turned on, but its settings or something it needs are wrong. |
| Nothing about it | Not installed in the environment Hive runs from: check step 1. |

To see the log without a terminal, turn on Settings → Developer → Runtime logs in the dashboard.
`GET /api/channels` also lists each installed channel as `running`, `off` or `failed`.

To write a package of your own, see [Building on Hive](building-on-hive.md).

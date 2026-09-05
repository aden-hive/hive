# Using Aden Hive with Kilo Code CLI

This directory enables the use of **Kilo Code CLI** as an alternative coding agent surface for the Aden Hive framework, alongside Claude Code and Cursor.

Kilo Code supports automatic discovery of Hive skills using the same `SKILL.md` convention already used in this repository.

---

## 1. Install Kilo Code CLI

### Prerequisites
- Node.js 18 or newer

Verify Node.js:
```bash
node --version
````

### Install Kilo CLI globally

```bash
npm install -g @kilocode/cli
```

Verify installation:

```bash
kilo --version
```

If the command is not found, ensure your global npm bin directory is on your `PATH`.

---

## 2. First-Time Setup (Required Once)

Kilo Code uses a global configuration file stored at:

```
~/.kilocode/config.json
```

This setup is required only once per machine.

### Step 1: Start Kilo

```bash
kilo
```

### Step 2: Connect an LLM provider

Inside the Kilo interface, run:

```
/connect
```

Select a provider (OpenAI, Anthropic, OpenRouter, Gemini, etc.) and enter your API key when prompted.

> ⚠️ This setup is independent of Hive’s `quickstart.sh`.
> No changes to `quickstart.sh` are required.


## 3. Running Hive Skills with Kilo

All Hive skills for Kilo live under:

```
.kilo/skills/
```

Kilo automatically discovers these skills at runtime.

---

## 4. List Available Hive Skills

From the root of the Hive repository, start Kilo:

```bash
kilo
```

Then list available skills:

```
/skills
```

This will display all discovered Hive skills, such as:

* `/hive`
* `/hive-create`
* `/hive-test`
* `/hive-debugger`
* `/hive-concepts`
* `/hive-patterns`

---

## 5. Build a New Agent (hive-create)

To build a new agent from scratch:

```
kilo
/skills
/hive-create
```

Then describe the agent you want to build, for example:

```
Build an agent that monitors a directory and reports file changes.
```

The generated agent will be created under:

```
exports/<agent_name>/
```

---

## 6. Test an Existing Agent (hive-test)

To generate and run tests for an existing agent:

```
kilo
/skills
/hive-test
```

Example prompt:

```
Test the agent at exports/my_agent.
```

---

## 7. Debug a Failing Agent (hive-debugger)

To diagnose and fix a failing or stuck agent:

```
kilo
/skills
/hive-debugger
```

Example prompt:

```
My agent at exports/my_agent is failing at runtime.
```

---

## 8. Notes & Best Practices

* Kilo uses the same `SKILL.md` format as Claude Code and Cursor
* Skill names are derived from their folder names
* Always run Kilo from the repository root
* Generated agents are written to the `exports/` directory
* No Hive core code or setup scripts need to be modified

---

## Summary

1. Install Kilo Code CLI
2. Run `kilo` and complete `/connect` once
3. Start Kilo from the Hive repository
4. Use `/skills` to list available Hive skills
5. Invoke skills directly (e.g. `/hive-create`, `/hive-test`, `/hive-debugger`)

Kilo Code is now a fully supported alternative coding surface for Aden Hive.

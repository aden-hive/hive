# Demo Script (10-15 minutes)

Use this to show the template's value quickly.

## 1) Setup

```bash
./quickstart.sh
```

## 2) Copy template to exports

```bash
cp -r examples/templates/oss_contributor_accelerator exports/oss_contributor_accelerator
```

## 3) Run in TUI

```bash
hive run exports/oss_contributor_accelerator --tui
```

## 4) Suggested demo input

- Repo: `aden-hive/hive`
- Skills: `Python, agent frameworks, test automation, docs`
- Time: `6 hours/week`
- Preference: `quick win with meaningful impact`

## 5) Success signal

Agent should produce:
- ranked shortlist of 8 issues
- user-selected 1-3 issues
- `contribution_brief.md` with implementation + tests + PR draft text

## 6) What to share with reviewers

- Brief screenshot/video of issue ranking
- Final contribution_brief.md artifact
- One concrete issue picked and implemented from the brief

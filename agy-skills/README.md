# Antigravity (agy) skills

Skills for the **Antigravity CLI**, not for Claude Code. They deploy to
`~/.gemini/config/skills/<name>/SKILL.md`, which is Antigravity's global
customization root, and become slash commands in any workspace.

Kept separate from `../skills/` deliberately: that directory holds Claude Code
skills and installs to `~/.claude/skills/`. `../skills/antigravity/` is a Claude
skill *about* driving agy; the two are not interchangeable.

| Skill | Command | Purpose |
|---|---|---|
| `fwa` | `/fwa` | Execute a plan by delegating implementation/review work to ChatGPT CDP or Perplexity CoderPX; agy is implementation fallback only. |
| `coderpx` | `/coderpx` | Route agy plan, implementation and PR-review work across ChatGPT Sol and the allowed Perplexity models, then report ownership. |

## Install

`install/install.ps1` and `install/install.sh` copy these when
`~/.gemini/config` exists. To place them by hand:

```bash
cp -R agy-skills/fwa      ~/.gemini/config/skills/fwa
cp -R agy-skills/coderpx  ~/.gemini/config/skills/coderpx
```

## Verify

Discovery and content loading are separate things — check both:

```bash
agy -p "List every skill you can invoke as a slash command." --model gemini-3.7-flash --effort low
agy -p "/coderpx State the plan-routing rule only; do not submit external work." --model gemini-3.7-flash --effort low
```

The second must answer that agy never writes plans: primary is ChatGPT CDP Sol
Pro, then verified Sol Extra High, then GLM 5.3 with Reasoning through
Perplexity CoderPX. A run that lists the skill but cannot answer that has found
the file without reading it.

## Frontmatter contract

`name` and `description` are both required. `description` is what the agent
reads to decide whether to activate the skill, so it must say what the skill
does *and when to use it*. Reference: the builtin `agy-customizations` skill,
`docs/skills.md`.

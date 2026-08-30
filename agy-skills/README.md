# Antigravity (agy) skills

Skills for the **Antigravity CLI**, not for Claude Code. They deploy to
`~/.gemini/config/skills/<name>/SKILL.md`, which is Antigravity's global
customization root, and become slash commands in any workspace.

Kept separate from `../skills/` deliberately: that directory holds Claude Code
skills and installs to `~/.claude/skills/`. `../skills/antigravity/` is a Claude
skill *about* driving agy; the two are not interchangeable.

| Skill | Command | Purpose |
|---|---|---|
| `fwa` | `/fwa` | Execute a pasted plan or handoff: implement easy slices locally, push hard ones to ChatGPT CDP or CoderPX, verify, land. |
| `coderpx` | `/coderpx` | One bounded submit to a Perplexity picker model; the task kind (implement / review / plan / grill) is inferred from conversation context. |

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
agy -p "/coderpx Is GPT-5.6 Sol available? Answer in one sentence." --model gemini-3.7-flash --effort low
```

The second must answer that Sol is unavailable because the subscription is
Perplexity Pro rather than Max. A run that lists the skill but cannot answer
that has found the file without reading it.

## Frontmatter contract

`name` and `description` are both required. `description` is what the agent
reads to decide whether to activate the skill, so it must say what the skill
does *and when to use it*. Reference: the builtin `agy-customizations` skill,
`docs/skills.md`.

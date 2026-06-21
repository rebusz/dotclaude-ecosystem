---
name: frontend-house-rules
description: House rules layered on top of the taste-skill family (design-taste-frontend, gpt-taste, minimalist-ui, redesign-existing-projects) for ALL web / UI / frontend work. Honor a project-root .taste.json for the design dials, keep the em-dash ban scoped to generated UI text only (never chat/commits/footers), and enforce prefers-reduced-motion across every variant including gpt-taste. Load whenever building, styling, or redesigning any web interface with a taste skill active.
---

# Frontend house rules — taste-skill overlay

Applies on top of any taste-skill variant (`design-taste-frontend`, `gpt-taste`,
`minimalist-ui`, `redesign-existing-projects`). On conflict, these rules win over the base
skill. They do **not** replace it — the base skill still drives the actual design.

## 1. Project dials via `.taste.json`
Before applying the taste dials, look for a `.taste.json` at the project root (search the
working dir upward to the repo root). If present, its values **override** the skill's
in-prompt defaults — so a repo pins its house style once instead of re-stating dials each
prompt:
```json
{
  "DESIGN_VARIANCE": 5,    // 1 = symmetry .. 10 = artsy chaos
  "MOTION_INTENSITY": 2,   // 1 = static .. 10 = cinematic / physics
  "VISUAL_DENSITY": 8,     // 1 = airy .. 10 = packed data
  "motion": "off"          // optional kill-switch: "off" => MOTION_INTENSITY=1 and NO entrance/scroll/auto animation anywhere
}
```
If there is no `.taste.json`, fall back to the brief and the skill defaults.

## 2. Em-dash ban scope (clarification)
The taste skills ban the em-dash (`—`) completely — but that ban governs **generated UI /
page content and design assets**: headlines, eyebrows, pills, body copy, quotes, attribution,
captions, button text, alt text, and any rendered string. It does **NOT** govern the agent's
own non-page output: conversational replies, commit messages, PR descriptions, code comments,
or the operator's metadata footer. Do not strip em-dashes from those. Keep the ban where it
belongs — in the shipped UI text — and leave normal punctuation everywhere else.

## 3. Reduced-motion everywhere (including gpt-taste)
`prefers-reduced-motion: reduce` compliance is mandatory for **every** taste variant, not just
`design-taste-frontend`. Any animation (GSAP, Motion, CSS, scroll-hijack, parallax, magnetic
physics, perpetual loops) MUST collapse to static / instant under reduced motion. When
`.taste.json` sets `"motion": "off"`, treat the whole project as reduced-motion: no entrance,
scroll-reveal, or auto-animation regardless of the variant's defaults or the brief.

## Precedence
`.taste.json` > these house rules > the base taste skill. On real-time financial / trading
surfaces, `tsu-dashboard-taste` (when present) overrides all of the above for live-data
elements.

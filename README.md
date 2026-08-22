# ELI5 for Codex

A Codex-native version of the ELI5 workflow shared by Thariq Shihipar: turn a difficult topic into a self-contained HTML explainer with big visuals, few words, and a clear step-by-step story.

## What it does

Ask Codex for an ELI5 explanation and the plugin creates a finished `.html` file you can open or share immediately. The artifact uses inline CSS, JavaScript, and SVG, so it needs no build step and does not depend on a hosted service.

Examples:

```text
Use $eli5 to explain how DNS works.
Explain compound interest as a visual ELI5 page.
Turn this architecture diagram into a beginner-friendly walkthrough.
```

## What it makes

[`example/eli5-how-does-dns-work.html`](example/eli5-how-does-dns-work.html) — produced by following this skill, then verified with the bundled checker.

| | |
| :--- | :--- |
| Steps | 7, one idea each |
| Words on the page | **98** (budget is 120) |
| Analogy | you know the shop's name, you need its street number |
| Assets | none — every drawing is inline SVG |
| Size | 9 KB, opens offline |

## Install

Add this repository as a Codex marketplace, then install the plugin:

```bash
codex plugin marketplace add zdrjson/codex-eli5 --ref main
codex plugin add codex-eli5@codex-eli5
```

Start a new Codex task after installation so the bundled skill is discovered.

## What the checker enforces

`check_html.py` is dependency-free and covers two families of failure.

**Not self-contained** — missing doctype / `lang` / title / viewport / inline style, or any asset loaded over the network (`src`, `href`, `srcset`, `poster`, `@import`, `url(https://…)`).

**Not picture-first** — the checks that stop an explainer from quietly degrading into a tidy wall of text:

- **Visible word budget**, default 120. Text inside `<script>` and `<style>` is excluded, so a page isn't punished for its own CSS. Override with `--max-words`, or `--max-words 0` to disable.
- **Every inline SVG needs an accessible name** — `aria-label`, `aria-labelledby`, or a `<title>` child; `aria-hidden="true"` if it's genuinely decorative. Nested `<svg>` counts once.

```bash
python3 plugins/codex-eli5/skills/eli5/scripts/check_html.py path/to/explainer.html
python3 plugins/codex-eli5/skills/eli5/scripts/check_html.py page.html --max-words 200
```

One thing the checker *can't* catch: SVG text that overflows its `viewBox` gets silently clipped, and static analysis won't see it. That one needs eyes on the rendered page — which is why the skill asks for a browser pass.

## Development

Run the dependency-free tests:

```bash
python3 -m unittest discover -s tests -v
```

10 tests, no third-party packages. They cover the self-contained checks, both picture-first checks, and the shipped example artifact.

## What changed in the port

The Claude original is three lines long, and it can afford to be: Claude renders **artifacts**, so "make an HTML explainer" already means something there. Codex has no artifact surface and no `$ARGUMENTS`, so parts of this had to be rebuilt rather than translated.

**Artifact → a real file.** Codex writes `outputs/eli5-<slug>.html` and opens it with `open` / `xdg-open` / `start`. That turns out to be an upgrade: the result is a file you can keep, email, or commit, not a panel that dies with the session.

**Self-contained became a hard requirement.** A Claude artifact runs behind a CSP that blocks external assets anyway. A file on disk has no such backstop, so the skill states it outright and the checker enforces it.

**`$ARGUMENTS` → read the turn.** Codex skills take no arguments; the skill reads the topic from the user's message and asks if it arrives bare.

**The design brief is spelled out, and machine-checked.** This is the part that matters most. Claude reaches for a visual layout on its own; Codex is tuned as a coding agent and will hand you a tidy, text-heavy document unless told otherwise. So the constraints are explicit — ~12 words per step and 120 per page, cover-the-text-and-it-still-reads, one analogy held to the end, the moving thing keeping one colour and one shape throughout — and the two that can be checked statically are wired into `check_html.py`, because a rule nothing enforces is a suggestion.

## Credits

Inspired by Anthropic's [`eli5`](https://github.com/anthropics/claude-plugins-community/tree/main/eli5) community plugin, shared by [Thariq Shihipar](https://x.com/trq212/status/2090884854590382515). This repository is an independent Codex adaptation with expanded artifact, accessibility, and verification guidance.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

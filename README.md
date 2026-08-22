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

## Install

Add this repository as a Codex marketplace, then install the plugin:

```bash
codex plugin marketplace add zdrjson/codex-eli5 --ref main
codex plugin add codex-eli5@codex-eli5
```

Start a new Codex task after installation so the bundled skill is discovered.

## Development

Run the dependency-free tests:

```bash
python3 -m unittest discover -s tests -v
```

Validate a generated explainer:

```bash
python3 plugins/codex-eli5/skills/eli5/scripts/check_html.py path/to/explainer.html
```

## Credits

Inspired by Anthropic's [`eli5`](https://github.com/anthropics/claude-plugins-community/tree/main/eli5) community plugin. This repository is an independent Codex adaptation with expanded artifact, accessibility, and verification guidance.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

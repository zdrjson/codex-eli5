# OpenAI public-directory submission pack

This folder contains the copy-ready material for the initial skills-only submission of ELI5 for Codex.

## Portal choices

- Submission type: **Skills only**
- Availability: all countries and regions offered by the portal
- Authentication or reviewer credentials: none
- MCP server: none
- Custom UI or screenshots: none

Use `listing.json` for the Info, Prompts, Global, and Release notes tabs. Use `test-cases.json` for the five positive and three negative reviewer cases.

The visual-reference test uses the fixed public fixture at `fixtures/reference-explainer.png` so every reviewer can reproduce the same input.

## Upload bundle

Create the final ZIP from the repository's `plugins` directory so the archive has exactly one top-level plugin folder:

```bash
mkdir -p ../dist
zip -r ../dist/codex-eli5-0.2.3.zip codex-eli5 -x "*/__pycache__/*" "*.pyc" ".DS_Store"
```

The resulting archive must start with `codex-eli5/.codex-plugin/plugin.json` and must not include the repository marketplace, tests, examples, or submission notes.

## Final checks

- Run the repository unit tests and the official plugin validator.
- Confirm all four public URLs return HTTPS success responses.
- Upload `dist/codex-eli5-0.2.3.zip` in the Skills tab.
- Wait for the skill security scan to pass.
- Review the draft and policy attestations before selecting **Submit for Review**.

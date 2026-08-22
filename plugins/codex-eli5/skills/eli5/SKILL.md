---
name: eli5
description: Create self-contained visual HTML explainers for beginners. Use when the user says ELI5, asks to explain a topic simply, or wants a picture-first walkthrough; skip it for ordinary short answers when an artifact would not help.
---

# ELI5

Turn the user's topic into a polished HTML explainer for someone starting from zero. Use plain language without talking down to the reader.

Codex skills take no arguments, so read the topic from the user's message. If the skill is invoked bare, ask what they want explained and stop there.

## Shape the explanation

- Identify the one idea the reader should remember.
- If the topic refers to "this" or "the" system, inspect the relevant workspace code and docs first. Do not invent implementation details; when no specific system is available, clearly label the explanation as a typical example.
- Choose one concrete analogy — something the reader has physically touched: mail, water pipes, a restaurant kitchen, a bouncer at a door. **Hold it to the end.** Switching metaphors halfway is the most common way these pages fail. Then show where the analogy stops being exact.
- Teach the mechanism in 3–6 visual steps, in the order the thing actually happens. Each step answers one question.
- Match the user's language. Define necessary jargon at first use.
- Verify time-sensitive or high-stakes facts with appropriate primary sources before presenting them. For medical, legal, or financial topics, keep the artifact educational and state its limits.

## The two rules that make it picture-first

Everything below is style. These two are the mechanism.

**Pictures carry the explanation; words only label it.**
Cover the text on any step — it should still make sense. If it doesn't, that step is decorated, not explained.

**Word budget: about 12 words per step, 120 word units on the page.**
This is the hard part and the whole point. When the words won't fit, you haven't found the picture yet — go back and find it, rather than raising the budget. The checker counts whitespace-delimited words and counts CJK characters individually; raise `--max-words` only when the user asked for something genuinely longer.

Two habits that do most of the work:

- Give the moving thing — the packet, the request, the electron, the dollar — **one colour and one shape, identical in every step it appears in.** That consistency is what lets someone follow a mechanism without reading.
- Match the drawing to the idea: sequence → boxes and arrows left to right; before/after → two panels, identical framing, one thing changed; part/whole → one shape broken into labelled pieces; scale → two objects at true relative size (never a number without a picture beside it); loop → arrows returning to the start with the repeating step highlighted.

## Build the artifact

Create one UTF-8 HTML file. Save it where the user requests; otherwise use `outputs/eli5-<topic-slug>.html` in the current workspace.

The page must:

- work by opening the file directly, with no build step;
- keep CSS, JavaScript, and SVG in the file;
- avoid local or network-loaded fonts, libraries, images, data files, and trackers unless the user explicitly requests them; if they do, disclose that the page is no longer fully self-contained;
- place this supported restrictive policy in `<head>` before any style, script, or loadable element; it blocks background network and subresource loads missed by static checks, but it is not a sandbox and ordinary links or top-level navigation remain possible:

```html
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; base-uri 'none'; form-action 'none'; img-src data:; font-src data:; media-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
```

- use that exact policy for the normal self-contained artifact; only replace it when the user explicitly approved external resources, and then run the checker with `--allow-external`;
- use large, meaningful visuals and very little text — step titles around 28–40px, each drawing filling most of its panel, a visible number per step;
- be responsive, keyboard-friendly, and readable with reduced motion enabled;
- include a descriptive title, language attribute, viewport metadata, visible focus states, and text alternatives for non-decorative visuals — every inline SVG needs `aria-label`, `aria-labelledby`, or a `<title>` child, or `aria-hidden="true"` if it is purely decorative;
- set an explicit `background` on `body` and an explicit colour on every SVG stroke and fill, so the page holds up in both light and dark browsers;
- avoid horizontal scrolling at phone width;
- end with a compact recap or a simple check-for-understanding interaction.

Prefer inline SVG, CSS diagrams, familiar icons, and spatial layouts over paragraphs. An emoji is an acceptable fallback for a small object, but a drawn shape beats one every time — an emoji is a sticker, an SVG is an explanation. Decoration should support the idea rather than compete with it.

Keep SVG text inside its `viewBox`: a centred label whose anchor sits near the edge gets silently clipped, and it will not show up in any automated check.

## Verify and hand off

Resolve the directory containing this `SKILL.md`, then run its bundled checker with Python 3.9 or newer:

```bash
python3 "<this-skill-directory>/scripts/check_html.py" "<generated-file.html>"
```

On Windows, use `py -3` or `python` when `python3` is unavailable. If the user explicitly approved external resources, add `--allow-external`. If Python is unavailable, perform the same checks manually and report that the bundled checker did not run.

When browser or screenshot tools are available, inspect the rendered page at phone and desktop sizes, in both colour schemes. Fix clipped content, unreadable text, broken controls, missing focus states, and console errors. Otherwise, say plainly that visual rendering was not verified.

Then show the file in the current workspace UI when that surface is available. Otherwise open it with the platform's normal command:

```bash
open <file>        # macOS
xdg-open <file>    # Linux
Start-Process <file>  # Windows PowerShell
```

Return a link to the finished HTML file and one sentence naming the analogy you used. Do not paste the entire HTML into chat unless the user asks — the page is the deliverable.

## Before you call it done

- [ ] The checker passes.
- [ ] Every step still reads with its text covered.
- [ ] One analogy runs from the first step to the last.
- [ ] The moving thing looks identical in every step it appears in.
- [ ] Opened in a browser and actually looked at it, at phone width too.

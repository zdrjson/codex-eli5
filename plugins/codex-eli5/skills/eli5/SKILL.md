---
name: eli5
description: Create self-contained visual HTML explainers for beginners. Use when the user says ELI5, asks to explain a topic simply, or wants a picture-first walkthrough; skip it for ordinary short answers when an artifact would not help.
---

# ELI5

Turn the user's topic into a polished HTML explainer for someone starting from zero. Use plain language without talking down to the reader.

## Shape the explanation

- Identify the one idea the reader should remember.
- If the topic refers to "this" or "the" system, inspect the relevant workspace code and docs first. Do not invent implementation details; when no specific system is available, clearly label the explanation as a typical example.
- Choose one concrete analogy, then show where the analogy stops being exact.
- Teach the mechanism in 3–6 visual steps. Each step should answer one question.
- Match the user's language. Define necessary jargon at first use.
- Verify time-sensitive or high-stakes facts with appropriate primary sources before presenting them. For medical, legal, or financial topics, keep the artifact educational and state its limits.

## Build the artifact

Create one UTF-8 HTML file. Save it where the user requests; otherwise use `outputs/eli5-<topic-slug>.html` in the current workspace.

The page must:

- work by opening the file directly, with no build step;
- keep CSS, JavaScript, and SVG in the file;
- avoid network-loaded fonts, libraries, images, and trackers unless the user explicitly requests them;
- use large, meaningful visuals and very little text;
- be responsive, keyboard-friendly, and readable with reduced motion enabled;
- include a descriptive title, language attribute, viewport metadata, visible focus states, and text alternatives for non-decorative visuals;
- avoid horizontal scrolling at phone width;
- end with a compact recap or a simple check-for-understanding interaction.

Prefer inline SVG, CSS diagrams, familiar icons, and spatial layouts over paragraphs. Decoration should support the idea rather than compete with it.

## Verify and hand off

Run the bundled checker:

```bash
python3 <this-skill-directory>/scripts/check_html.py <generated-file.html>
```

When browser or screenshot tools are available, inspect the rendered page at phone and desktop sizes. Fix clipped content, unreadable text, broken controls, missing focus states, and console errors. Otherwise, say that visual rendering was not verified.

Return a link to the finished HTML file and a one-sentence summary of the teaching approach. Do not paste the entire HTML into chat unless the user asks.

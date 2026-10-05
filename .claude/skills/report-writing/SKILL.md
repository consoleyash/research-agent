---
name: report-writing
description: Convert gathered research into a clear, professional Markdown report and save it to a file. Use this skill after web research is complete, when it is time to write the final .md report.
---

# Report Writing Skill

## Purpose

Convert gathered research into a clear, professional Markdown report
and save it with the `Write` tool to the output path given in the task.

## Structure

Use the following structure when appropriate. Omit a section only when it
genuinely does not apply to the topic (for example, "Market / Competitive
Context" for a purely scientific question).

```markdown
# [Report Title]

*Generated: [date] — Topic: [the user's research question]*

## Executive Summary

Brief summary of the most important findings (3-6 sentences).

## Key Findings

Bulleted list of the major findings. Each bullet is one finding with an
inline citation, e.g. `[1]`.

## Detailed Analysis

Present the evidence and analysis, organized under sub-headings that follow
the sub-questions of the research.

## Data / Metrics

Use Markdown tables when numerical comparisons are useful.

## Market / Competitive Context

Include relevant comparisons when requested or clearly relevant.

## Risks and Limitations

Identify important limitations in the available data, conflicting sources,
and open questions.

## Outlook

Discuss future implications only when supported by available evidence.

## Sources

Numbered list of the sources used, matching the inline citation numbers:
`1. [Title](URL) — Publisher, date`
```

## Formatting Rules

- Use Markdown.
- Use numbered inline citations like `[1]`, `[2]` that map to the Sources list.
- Prefer tables for structured numerical information.
- Keep paragraphs concise (2-5 sentences).
- Do not repeat the same information across sections.
- Clearly distinguish sourced facts from interpretation
  (e.g. "Analysis:" or "Interpretation:" prefixes for your own inference).
- Never fabricate statistics or sources. Only cite URLs that were actually
  found during research.
- Write the complete report in a single `Write` call to the requested path.
  Do not print the full report to the conversation; after writing, reply with
  a one-paragraph summary and the path of the file.

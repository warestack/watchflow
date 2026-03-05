"""
Prompt template for the Rule Extractor Agent.
"""

EXTRACTOR_PROMPT = """
You are an expert at reading AI assistant guidelines and coding standards (e.g. Cursor rules, Claude instructions, Copilot guidelines, .cursorrules, repo rules).

Your task: read the following markdown document and extract every distinct **rule-like statement** or guideline. Treat the document holistically: rules may appear as:
- Bullet points or numbered lists
- Paragraphs or full sentences
- Section headings plus body text
- Implicit requirements (e.g. "PRs should be small" or "we use conventional commits")
- Explicit markers like "Rule:", "Instruction:", "Always", "Never", "Must", "Should"

For each rule you identify, output one clear, standalone statement (a single sentence or short phrase). Preserve the intent; normalize wording only if it helps clarity. Do not merge unrelated rules. If there are no rules or guidelines, return an empty list.

Markdown content:
---
{markdown_content}
---

Output the list of rule statements. Do not include explanations or numbering in the statements themselves.
"""

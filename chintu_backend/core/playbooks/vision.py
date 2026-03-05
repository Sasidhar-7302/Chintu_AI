"""Vision playbooks (prompt templates).

These prompts are used by local vision backends (Ollama/Gemini) to extract
structured data from screenshots.
"""

ANALYZE_SCREEN_JSON_PROMPT = """You are a UI analysis engine for desktop screenshots.
Return ONLY valid JSON (no markdown, no code fences) with this schema:
{
  "success": true,
  "description": "1-2 sentence summary of the active app/page and the main visible content",
  "elements": [
    {"name": "Search box", "type": "input", "location": "top-center", "text": ""}
  ],
  "text_content": "important readable text snippets visible on screen",
  "actions": ["type in search box", "click submit button"]
}

Rules:
- Keep max 8 elements.
- Use concise element names.
- If uncertain, return best-effort values instead of empty output.
- Do not use placeholder strings like "optional visible text" or "N/A".
- Always return all keys above."""

DESCRIBE_SCREEN_PROMPT = """Look at this screenshot and give me a brief, natural description.
Speak as if you're telling someone what's on their screen.
Keep it to 2-3 sentences. Be specific about the app/website and main content."""


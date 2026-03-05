# Browser-as-Model Fallback

The browser fallback connects to an existing Chrome session using CDP so it can reuse your logged-in ChatGPT/Gemini cookies.

1) Launch Chrome with a debugging port:
   chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\Users\YourUser\AppData\Local\Google\Chrome\User Data"
2) Enable fallback in `.env`:
   CHINTU_BROWSER_FALLBACK_ENABLED=true
   CHINTU_BROWSER_CDP_URL=http://localhost:9222
   CHINTU_BROWSER_FALLBACK_URL=https://chatgpt.com

Notes
- Keep the Chrome window open while using fallback.
- If Playwright is missing: `pip install playwright && playwright install chromium`.

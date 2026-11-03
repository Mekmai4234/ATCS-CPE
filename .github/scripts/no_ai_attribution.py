"""Fail when commits (or a PR title/body) carry AI-tool attribution.

Checks every commit in a git range for co-author trailers, "Generated with"
footers and author/committer identities of AI coding tools. Mentions of model
names in normal text (for example the Gemini API this project uses) are fine.

  python .github/scripts/no_ai_attribution.py BASE..HEAD
  PR_TEXT="title + body" python .github/scripts/no_ai_attribution.py BASE..HEAD
"""

import os
import re
import subprocess
import sys

TOOLS = r"(claude|anthropic|codex|openai|chatgpt|copilot|cursor|devin|windsurf|aider)"
LINE_RULES = [
    re.compile(rf"^\s*co-authored-by:.*{TOOLS}", re.I),
    re.compile(r"generated (with|by) \[?(claude|codex|chatgpt|copilot|cursor)", re.I),
    re.compile(r"^\s*🤖"),
    re.compile(r"^\s*claude-session:", re.I),
]
IDENTITY = re.compile(
    r"(@anthropic\.com|@openai\.com|^(claude|codex|chatgpt|copilot|devin)( |$))", re.I
)


def problems_in_text(text):
    return [line.strip() for line in text.splitlines() if any(r.search(line) for r in LINE_RULES)]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    found = []
    if len(sys.argv) > 1:
        log = subprocess.run(
            ["git", "log", "--format=%H%x1f%an <%ae>%x1f%cn <%ce>%x1f%B%x1e", sys.argv[1]],
            capture_output=True, text=True, encoding="utf-8", check=True,
        ).stdout
        for record in filter(str.strip, log.split("\x1e")):
            sha, author, committer, body = record.strip().split("\x1f", 3)
            for who in (author, committer):
                if IDENTITY.search(who):
                    found.append(f"{sha[:8]} identity: {who}")
            found += [f"{sha[:8]} message: {line}" for line in problems_in_text(body)]
    found += [f"PR text: {line}" for line in problems_in_text(os.environ.get("PR_TEXT", ""))]
    for item in found:
        print(item)
    print(f"{len(found)} AI attribution finding(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

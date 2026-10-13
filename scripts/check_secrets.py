"""Fails when a tracked file contains something that looks like a real credential.

Run in CI and before publishing: python scripts/check_secrets.py
Placeholders such as "sk-ant-..." are allowed; real keys, private keys and tokens are not.
"""

from __future__ import annotations

import re
import subprocess
import sys

PATTERNS = {
    "Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}"),
    "Cloudflare API token": re.compile(r"(?i)cloudflare[^\n]{0,20}token[^\n]{0,5}[=:]\s*['\"]?[A-Za-z0-9_-]{40}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "admin key assignment": re.compile(r"(?m)^\s*ADMIN_KEY\s*=\s*['\"]?[A-Za-z0-9_-]{24,}"),
}


def main() -> int:
    files = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, text=True, check=True).stdout.splitlines()
    problems = []
    for path in files:
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(text):
                problems.append(f"{path}: {name}")
    for p in problems:
        print("SECRET?", p)
    print("no secrets found" if not problems else f"{len(problems)} possible secret(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

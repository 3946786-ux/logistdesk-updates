from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHANNEL = ROOT / "update_channel.json"


def normalize(value: str) -> str:
    value = value.strip().strip("/")
    value = re.sub(r"^https?://github\.com/", "", value, flags=re.I)
    value = re.sub(r"\.git$", "", value, flags=re.I)
    parts = [p for p in value.split("/") if p]
    if len(parts) != 2:
        raise ValueError("Нужно указать owner/repository, например timur/logistdesk-updates")
    owner, repo = parts
    allowed = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not allowed.fullmatch(owner) or not allowed.fullmatch(repo):
        raise ValueError("В owner/repository есть недопустимые символы")
    return f"{owner}/{repo}"


def main() -> int:
    raw = " ".join(sys.argv[1:]).strip()
    if not raw:
        raw = input("GitHub repository (owner/repository): ").strip()
    try:
        repo = normalize(raw)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    manifest_url = f"https://github.com/{repo}/releases/latest/download/latest.json"
    CHANNEL.write_text(json.dumps({"manifest_url": manifest_url}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("OK")
    print("Repository:", repo)
    print("Manifest:", manifest_url)
    print("Saved:", CHANNEL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

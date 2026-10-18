#!/usr/bin/env python3
"""Confronta l'installer con RT 4.3.0 e riporta la misura nel riepilogo della CI."""
import json
import os
from pathlib import Path
import sys
import urllib.request


def main():
    target = sys.argv[1]
    suffix = "macos-arm64.dmg" if target == "macos" else "windows-x64-setup.exe"
    current = next(Path("dist").glob(f"RT-*-{suffix}"))
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "RT-installer-size"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request("https://api.github.com/repos/atturk/rt/releases/tags/v4.3.0", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    before = next(asset["size"] for asset in release["assets"] if asset["name"] == f"RT-4.3.0-{suffix}")
    after = current.stat().st_size
    delta = after - before
    report = (f"{target}: RT 4.3.0 {before / (1 << 20):.2f} MiB → "
              f"{after / (1 << 20):.2f} MiB ({delta / (1 << 20):+.2f} MiB).")
    print(report)
    current.with_suffix(current.suffix + ".size.json").write_text(
        json.dumps({"target": target, "before": before, "after": after, "delta": delta}) + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(report + "\n")
    if delta > 10 * (1 << 20):
        raise SystemExit("L'installer è cresciuto di oltre 10 MiB rispetto a RT 4.3.0.")


if __name__ == "__main__":
    main()

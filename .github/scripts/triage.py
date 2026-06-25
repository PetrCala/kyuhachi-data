#!/usr/bin/env python3
"""Decide whether catalog drift warrants a nudge, and render the issue body.

Run by `.github/workflows/catalog-detect.yml` after `catalog_sync.py detect`. Reads the
freshest `reports/<ts>/changelog.json` plus `data/snapshot.next.json`, writes decision
flags to `$GITHUB_OUTPUT`, and renders the nudge body to `issue_body.md`. Stdlib only.

Decision:
  fire    = any material mover  OR  any added  OR  any removed   → open/refresh the nudge
  seed_ok = the map seed was fetched this run (membership detection was live)
"""
from __future__ import annotations

import glob
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]  # .github/scripts/ -> repo root


def latest_changelog():
    reps = sorted(glob.glob(str(ROOT / "reports" / "*" / "changelog.json")))
    if not reps:
        return None, None
    p = pathlib.Path(reps[-1])
    return json.loads(p.read_text(encoding="utf-8")), p.parent


def seed_ok() -> bool:
    try:
        meta = json.loads((ROOT / "data" / "snapshot.next.json").read_text(encoding="utf-8"))
        return bool(meta.get("_meta", {}).get("seed", False))
    except FileNotFoundError:
        return False


def main() -> int:
    cl, repdir = latest_changelog()
    cl = cl or {"modified": [], "added": [], "removed": [], "counts": {}}
    material = [m for m in cl.get("modified", []) if m.get("severity") == "material"]
    added = cl.get("added", [])
    removed = cl.get("removed", [])
    fire = bool(material or added or removed)
    sk = seed_ok()

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"fire={'true' if fire else 'false'}\n")
            f.write(f"seed_ok={'true' if sk else 'false'}\n")

    prompt = (ROOT / ".github" / "catalog-prep-prompt.md").read_text(encoding="utf-8")
    summ = ""
    if repdir and (repdir / "summary.md").exists():
        summ = (repdir / "summary.md").read_text(encoding="utf-8")
    body = "\n".join([
        prompt,
        "\n---\n",
        "## What detection saw this cycle\n",
        f"- material movers: **{len(material)}**",
        f"- added (new onsens): **{len(added)}**",
        f"- removed / delisted: **{len(removed)}**",
        "",
        "<details><summary>catalog-diff summary.md</summary>\n",
        summ,
        "\n</details>",
    ])
    (ROOT / "issue_body.md").write_text(body, encoding="utf-8")
    print(f"fire={fire} seed_ok={sk} "
          f"material={len(material)} added={len(added)} removed={len(removed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

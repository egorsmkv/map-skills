#!/usr/bin/env python3
"""Copy the canonical validator into every skill so each stays self-contained.

Skills get copied into ~/.claude/skills and must run without this workspace, so
each carries its own copy of write_csv.py (PEP 723 header => `uv run` resolves
pydantic on its own). Edit src/maps_csv/write_csv.py, then run this.

    uv run scripts/sync_skills.py          # copy
    uv run scripts/sync_skills.py --check  # verify copies are current (CI)
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "maps_csv" / "write_csv.py"
SKILLS = sorted(p for p in ROOT.glob("*-scrape") if (p / "SKILL.md").exists())


def main() -> int:
    check = "--check" in sys.argv
    want = SOURCE.read_text(encoding="utf-8")
    stale = []
    for skill in SKILLS:
        target = skill / "scripts" / "write_csv.py"
        if target.exists() and target.read_text(encoding="utf-8") == want:
            print(f"ok      {target.relative_to(ROOT)}")
            continue
        if check:
            stale.append(target.relative_to(ROOT))
            print(f"STALE   {target.relative_to(ROOT)}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE, target)
        target.chmod(0o755)
        print(f"synced  {target.relative_to(ROOT)}")

    if not SKILLS:
        print("no skills found", file=sys.stderr)
        return 1
    if stale:
        print(
            f"\n{len(stale)} copy(ies) out of date - run: uv run scripts/sync_skills.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""match.py <observe-dump.txt> [--json]

Parse an observe.sh dump and print the patterns whose signature fires,
ranked, each with its evidence lines and the pattern file's measured
history (rows, promote rate, median delta). The output is the first thing
the hypothesize step reads; it says which patterns the evidence supports,
not which one to pick.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from signatures import RULES  # noqa: E402

STAGE_ORDER = {"early": 0, "mid": 1, "late": 2, "unknown": 3}


def parse_observation(text: str) -> dict:
    obs = {"digests": [], "requests": [], "indexes": [], "bench_seconds": None}
    section = None
    for line in text.splitlines():
        if line.startswith("## "):
            head = line.lower()
            section = ("digests" if "digest" in head else "requests" if "request" in head
                       else "indexes" if "index" in head else "other")
            continue
        if not line.strip() or line.startswith("#"):
            continue
        if section == "digests":
            cols = line.split("\t")
            if len(cols) >= 6 and re.match(r"^[\d.]+$", cols[0]):
                obs["digests"].append({
                    "total_s": float(cols[0]), "calls": int(cols[1]), "avg_ms": float(cols[2]),
                    "rows_examined": int(cols[3]), "rows_sent": int(cols[4]), "query": "\t".join(cols[5:]).strip(),
                })
        elif section == "requests":
            m = re.match(r"^\s*(\d+)\s+\"?(\w+)\"?\s+(\S+)\s+(\d{3})\s*$", line)
            if m:
                obs["requests"].append({"count": int(m.group(1)), "method": m.group(2),
                                        "path": m.group(3), "status": m.group(4)})
        elif section == "indexes":
            if re.match(r"^[\w]+\.[\w]+\(", line.strip()):
                obs["indexes"].append(line.strip())
    m = re.search(r"bench_seconds[:=]\s*(\d+)", text)
    if m:
        obs["bench_seconds"] = int(m.group(1))
    return obs


def read_pattern(pattern_id: str) -> dict:
    path = HERE / "patterns" / f"{pattern_id}.md"
    info = {"id": pattern_id, "name": pattern_id, "stage": "unknown", "cost": "?", "risk": "?",
            "signature": "", "measured": [], "path": str(path.relative_to(HERE.parent)) if path.exists() else None}
    if not path.exists():
        return info
    text = path.read_text()
    fm = re.search(r"^---\n(.*?)\n---", text, re.S)
    if fm:
        for line in fm.group(1).splitlines():
            m = re.match(r"^(\w+):\s*(.*)$", line)
            if m and m.group(1) in ("name", "stage", "cost", "risk", "signature"):
                info[m.group(1)] = m.group(2).strip()
    measured = re.search(r"## Measured\n(.*?)(?:\n## |\Z)", text, re.S)
    if measured:
        for row in measured.group(1).splitlines():
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if len(cells) >= 9 and cells[0] not in ("problem", "---") and not cells[0].startswith("-"):
                info["measured"].append(dict(zip(
                    ["problem", "experiment", "baseline", "candidate", "delta", "samples", "minutes", "rule", "final", "notes"],
                    cells)))
    return info


def summarize_measured(rows: list[dict]) -> str:
    if not rows:
        return "no measured row yet"
    deltas = []
    for r in rows:
        m = re.match(r"([+-]?\d+(?:\.\d+)?)%", r["delta"])
        if m:
            deltas.append(float(m.group(1)))
    promoted = sum(1 for r in rows if r["final"] == "promote")
    med = f", median delta {statistics.median(deltas):+.0f}%" if deltas else ""
    return f"{len(rows)} measured, {promoted} promoted{med}"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    text = Path(sys.argv[1]).read_text()
    as_json = "--json" in sys.argv
    obs = parse_observation(text)
    results = []
    for pid, rule in RULES.items():
        evidence, strength = rule(obs)
        if evidence:
            info = read_pattern(pid)
            results.append({**info, "evidence": evidence, "strength": round(strength, 2)})
    results.sort(key=lambda r: (STAGE_ORDER.get(r["stage"], 3), -r["strength"]))
    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    if not obs["digests"] and not obs["requests"]:
        print("no digest or request sections found; is this an observe.sh dump?")
        return 1
    print(f"observation: {len(obs['digests'])} digests, {len(obs['requests'])} request rows, {len(obs['indexes'])} indexes")
    if not results:
        print("no pattern signature fired; read the dump by hand and add a signature if a pattern is there")
        return 0
    for r in results:
        print()
        print(f"[{r['stage']}] {r['id']}  ({r['name']}; cost {r['cost']}, risk {r['risk']}; "
              f"{summarize_measured(r['measured'])})")
        for e in r["evidence"][:4]:
            print(f"  - {e}")
        if r["path"]:
            print(f"  -> {r['path']}")
        else:
            print("  -> no pattern file yet; knowledge/patterns/" + r["id"] + ".md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

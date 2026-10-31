#!/usr/bin/env python3
"""Prints the next task a person may start, checking every dependency across all task files.

    python3 scripts/next-task.py chirag        # or pavan, anshuman

Run `git pull` on develop first: the answer is only as fresh as your checkout.

Dependency syntax, on each task line after the title:  (needs: C3, C4, C5)
    C3              that task is done: [x] in its owner's file on develop
    C8 started      that task is claimed or done: [~] or [x]
    approval: Name  a person must confirm before you start; ask your human
    none            nothing to wait for
Exit code: 0 when a task is ready, 2 when everything left is blocked, 1 on bad input.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEAM = ROOT / "docs" / "team"
LINE = re.compile(r"^- \[(?P<state>[ ~x])\].*?\*\*(?P<id>[A-Z]\d+)\b(?P<title>[^*]*)\*\*\s*\(needs:\s*(?P<needs>[^)]*)\)")
DONE, CLAIMED, OPEN = "x", "~", " "


def load() -> tuple[dict[str, str], dict[str, list[tuple[str, str, str]]]]:
    states: dict[str, str] = {}
    tasks: dict[str, list[tuple[str, str, str]]] = {}
    for f in sorted(TEAM.glob("tasks-*.md")):
        person = f.stem.removeprefix("tasks-")
        for line in f.read_text(encoding="utf-8").splitlines():
            m = LINE.match(line)
            if m:
                states[m["id"]] = m["state"]
                title = re.sub(r"^\s*\(([^)]*)\)\s*:?\s*", r"[\1] ", m["title"]).strip(" :")
                tasks.setdefault(person, []).append((m["id"], title, m["needs"].strip()))
    return states, tasks


def unmet(needs: str, states: dict[str, str]) -> list[str]:
    waiting = []
    for raw in [n.strip() for n in needs.split(",") if n.strip()]:
        if raw.lower() == "none":
            continue
        if raw.lower().startswith("approval:"):
            waiting.append(f"approval from {raw.split(':', 1)[1].strip()} (ask your human)")
            continue
        task, _, mode = raw.partition(" ")
        state = states.get(task)
        if state is None:
            waiting.append(f"{task} (no such task: fix the needs line)")
        elif mode == "started" and state not in (CLAIMED, DONE):
            waiting.append(f"{task} to be started")
        elif mode != "started" and state != DONE:
            waiting.append(f"{task} to be done ({'in progress' if state == CLAIMED else 'not started'})")
    return waiting


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    states, tasks = load()
    person = sys.argv[1].lower()
    if person not in tasks:
        print(f"unknown person {person!r}; expected one of {', '.join(sorted(tasks))}")
        return 1
    mine = tasks[person]
    in_progress = [t for t in mine if states[t[0]] == CLAIMED]
    for tid, title, _ in in_progress:
        print(f"IN PROGRESS: {tid} {title}  (finish this first if it is yours)")
    blocked = []
    for tid, title, needs in mine:
        if states[tid] != OPEN:
            continue
        waiting = unmet(needs, states)
        if not waiting:
            print(f"NEXT: {tid} {title}")
            return 0
        blocked.append((tid, title, waiting))
    if not blocked:
        print("Nothing left to do in your file.")
        return 0
    print("BLOCKED: no task is ready. Do not start a blocked task or work around a missing dependency.")
    for tid, title, waiting in blocked:
        print(f"  {tid} {title}: waiting for {'; '.join(waiting)}")
    print("Pull develop again later, or tell your human what you are waiting for.")
    return 2


if __name__ == "__main__":
    sys.exit(main())

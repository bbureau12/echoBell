#!/usr/bin/env python3
"""
REID Harness for EchoBell

Goal:
- Feed an enrollment image (single closeup person)
- Capture visitor_id created/selected
- Feed one or more probe images
- Check whether they match the same visitor_id
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
import sys
from typing import Optional, List, Tuple


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# Adjust import path if you run from repo root
from packages.perception.vision import snapshot_and_detect


@dataclass(frozen=True)
class ActorMatch:
    object_id: int
    visitor_id: str
    visitor_kind: str
    similarity: float
    det_conf: float
    box: Tuple[int, int, int, int]


def choose_actor(vr) -> Optional[ActorMatch]:
    """
    Pick the most "reliable" person object for identity.
    Heuristic:
      - prefer known visitor
      - highest visitor_similarity
      - tie-break: detection conf
    """
    best: Optional[ActorMatch] = None

    for obj in getattr(vr, "objects", []) or []:
        if (obj.label or "").lower() != "person":
            continue

        vid = obj.props.get("visitor_id")
        if not vid:
            continue

        kind = str(obj.props.get("visitor_kind") or "")
        sim = float(obj.props.get("visitor_similarity") or 0.0)
        conf = float(obj.props.get("conf") or 0.0)
        box = tuple(obj.box) if getattr(obj, "box", None) else (0, 0, 0, 0)

        cand = ActorMatch(
            object_id=int(obj.object_id),
            visitor_id=str(vid),
            visitor_kind=kind,
            similarity=sim,
            det_conf=conf,
            box=box,  # type: ignore
        )

        def score(a: ActorMatch) -> tuple:
            # known beats new, then similarity, then conf
            known_bonus = 1 if a.visitor_kind == "known" else 0
            return (known_bonus, a.similarity, a.det_conf)

        if best is None or score(cand) > score(best):
            best = cand

    return best


def run_one(db_path: str, image_path: str, debug: bool) -> tuple:
    vr = snapshot_and_detect(db_path, image_path, debug=debug)
    actor = choose_actor(vr)
    return vr, actor


def main() -> int:
    if __debug__:
        import sys
        if len(sys.argv) == 1:
            sys.argv.extend([
                "--db", "data/doorbell.db",
                "--enroll", "data/police/sherriff.jpg",
                "--probe", "data/police/sherriff.jpg",
                "--min-sim", "0.80",
            ])
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Path to echobell sqlite db")
    ap.add_argument("--enroll", required=True, help="Enrollment image (closeup single person)")
    ap.add_argument("--probe", nargs="+", required=True, help="One or more probe images to test matching")
    ap.add_argument("--debug", action="store_true", help="Enable debug output in snapshot_and_detect")
    ap.add_argument("--min-sim", type=float, default=0.80, help="Similarity threshold you consider 'good'")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f"DB not found: {args.db}")
    if not os.path.exists(args.enroll):
        raise SystemExit(f"Enroll image not found: {args.enroll}")
    for p in args.probe:
        if not os.path.exists(p):
            raise SystemExit(f"Probe image not found: {p}")

    print("\n=== ENROLL ===")
    _vr, enroll_actor = run_one(args.db, args.enroll, debug=args.debug)
    if not enroll_actor:
        print("No person with visitor_id detected in enroll image.")
        print("Tip: ensure the image has a clear person and passes your quality gate.")
        return 2

    print(
        f"Enroll actor: visitor_id={enroll_actor.visitor_id} "
        f"kind={enroll_actor.visitor_kind} sim={enroll_actor.similarity:.3f} "
        f"conf={enroll_actor.det_conf:.3f} box={enroll_actor.box}"
    )

    target_vid = enroll_actor.visitor_id

    print("\n=== PROBES ===")
    ok = 0
    total = 0
    for probe_path in args.probe:
        total += 1
        _vr2, probe_actor = run_one(args.db, probe_path, debug=args.debug)
        if not probe_actor:
            print(f"[{probe_path}] No person with visitor_id detected.")
            continue

        same = (probe_actor.visitor_id == target_vid)
        sim_ok = (probe_actor.similarity >= args.min_sim)

        status = "MATCH" if same else "DIFF"
        qual = "GOOD" if sim_ok else "LOW"

        print(
            f"[{probe_path}] {status} ({qual}) "
            f"visitor_id={probe_actor.visitor_id} kind={probe_actor.visitor_kind} "
            f"sim={probe_actor.similarity:.3f} conf={probe_actor.det_conf:.3f} box={probe_actor.box}"
        )

        if same and sim_ok:
            ok += 1

    print("\n=== SUMMARY ===")
    print(f"Target visitor_id: {target_vid}")
    print(f"Passes (same visitor_id AND sim>= {args.min_sim}): {ok}/{total}")

    # Exit code: 0 if all probes passed, else 1
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

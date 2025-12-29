# tools/trusted_cli.py
from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path
import numpy as np
import cv2
import os
from collections import Counter
from typing import Optional, Tuple, List
from insightface.app import FaceAnalysis
from scipy import stats

# ---------- utils ----------
def now_ts() -> int:
    return int(time.time())

def l2_normalize(x: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(x))
    return x if n == 0 else (x / n)

def l2_normalize_rows(X: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(X, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return X / n

def scan_trusted_faces(args):
    """Command handler for scanning trusted faces from folders."""
    stats = Counter()
    conn = get_conn()
    root = Path(args.root).resolve()

    app = FaceAnalysis(name=args.model)
    app.prepare(ctx_id=-1, det_size=(640, 640))
    model_name = f"insightface:{args.model}"

    
    if not root.exists():
        print(f"Error: Directory does not exist: {root}")
        return
    
    model_name = args.model

    for person_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        person_name = person_dir.name
        trusted_id = get_or_create_trusted_person(
            conn,
            name=person_name,
            label=person_name,
        )

        embeddings: list[np.ndarray] = []

        for img_path in iter_images(person_dir):
            img = cv2.imread(str(img_path))
            if img is None:
                stats["unreadable"] += 1
                continue

            emb, reason = pick_single_good_face(app, img, min_score=args.min_score, min_px=args.min_px)

            stats[reason] += 1

            if emb is not None:
                embeddings.append(emb)

        if len(embeddings) < args.min_faces:
            print(f"[SKIP] {person_name}: only {len(embeddings)} usable faces (need {args.min_faces})")
            continue

        embs = l2_normalize_rows(np.stack(embeddings, axis=0))
        
        # Optionally dedupe
        if args.dedupe:
            embs = dedupe_embeddings(embs, dup_sim_threshold=args.dedupe_threshold)
            print(f"[INFO] {person_name}: after deduplication, {embs.shape[0]} embeddings remain")
        
        protos, _ = select_prototypes_farthest_first(
            embs,
            k=min(args.prototypes, embs.shape[0]),
        )

        # Delete old embeddings if rebuild flag is set
        if args.rebuild:
            deleted = db_delete_embeddings_for_person(
                conn,
                trusted_id=trusted_id,
                model_name=model_name,
            )
            if deleted > 0:
                print(f"[INFO] {person_name}: deleted {deleted} old embeddings")

        # Insert new embeddings
        for emb in protos:
            db_insert_embedding(
                conn,
                trusted_id=trusted_id,
                embedding_type="face",
                model_name=model_name,
                emb=emb,
                camera_id=args.camera_id,
                quality_score=1.0,
            )
        
        # Commit the transaction
        conn.commit()

        print(f"[OK] {person_name}: stored {len(protos)} prototypes from {len(embeddings)} faces")
        print(f"[{'OK' if len(protos) else 'SKIP'}] {person_name} (trusted_id={trusted_id})")
        print(f"  images scanned: {stats['ok'] + stats['no_good_face'] + stats['multiple_good_faces'] + stats['unreadable']}")
        print(f"  ok: {stats['ok']}")
        if stats["no_good_face"]:
            print(f"  skipped (no good face): {stats['no_good_face']}")
        if stats["multiple_good_faces"]:
            print(f"  skipped (multiple good faces): {stats['multiple_good_faces']}")
        if stats["unreadable"]:
            print(f"  unreadable: {stats['unreadable']}")

    
    conn.close()


def get_or_create_trusted_person(conn, *, name: str, label: str | None = None) -> int:
    row = conn.execute(
        "SELECT trusted_id FROM trusted_person WHERE name = ?",
        (name,),
    ).fetchone()

    if row:
        return int(row[0])

    cur = conn.execute(
        """
        INSERT INTO trusted_person (name, label, created_ts)
        VALUES (?, ?, ?)
        """,
        (name, label or name, int(time.time())),
    )
    return int(cur.lastrowid)

def select_prototypes_farthest_first(embs: np.ndarray, k: int) -> tuple[np.ndarray, list[int]]:
    X = l2_normalize_rows(embs.astype("float32"))
    N = X.shape[0]
    if N == 0:
        return X[:0], []
    if k >= N:
        return X, list(range(N))

    mean = l2_normalize_rows(X.mean(axis=0, keepdims=True))[0]
    sims_to_mean = X @ mean
    first = int(np.argmax(sims_to_mean))

    idxs = [first]
    min_dist = 1.0 - (X @ X[first])
    for _ in range(1, k):
        nxt = int(np.argmax(min_dist))
        idxs.append(nxt)
        dist_to_new = 1.0 - (X @ X[nxt])
        min_dist = np.minimum(min_dist, dist_to_new)

    return X[idxs], idxs

# ---------- DB hooks ----------
def get_conn():
    # Connect to the doorbell database in the data folder
    db_path = Path(__file__).resolve().parents[3] / "data" / "doorbell.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn

def db_add_trusted_person(conn, name: str) -> int:
    # SQLite example; adapt to your DB
    cur = conn.cursor()
    cur.execute("INSERT INTO trusted_person(name, created_ts) VALUES(?, ?)", (name, now_ts()))
    conn.commit()
    return int(cur.lastrowid)

def db_list_trusted_people(conn) -> list[tuple[int, str]]:
    cur = conn.cursor()
    cur.execute("SELECT trusted_id, name FROM trusted_person ORDER BY trusted_id")
    return [(int(r[0]), r[1] or "") for r in cur.fetchall()]

def db_insert_embedding(conn, *, trusted_id: int, embedding_type: str, model_name: str,
                       emb: np.ndarray, camera_id: int | None = None, quality_score: float = 1.0) -> None:
    emb = emb.astype("float32")
    emb = emb / max(float(np.linalg.norm(emb)), 1e-12)

    conn.execute(
        """
        INSERT INTO trusted_person_embedding
          (trusted_id, embedding_type, model_name, embedding_dim, embedding_blob, created_ts, quality_score, camera_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (trusted_id, embedding_type, model_name, int(emb.shape[0]), emb.tobytes(), now_ts(), float(quality_score), camera_id),
    )




IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    # assumes a and b are already L2-normalized
    return float(np.dot(a, b))

def dedupe_embeddings(embs: np.ndarray, *, dup_sim_threshold: float = 0.995) -> np.ndarray:
    """
    Keep a subset of embeddings where no kept embedding is too similar to another.
    embs must be (N,D) and L2-normalized.
    """
    if embs.shape[0] == 0:
        return embs

    kept: List[np.ndarray] = []
    for e in embs:
        if not kept:
            kept.append(e)
            continue
        # if e is almost identical to any kept embedding, drop it
        if max(cosine_similarity(e, k) for k in kept) >= dup_sim_threshold:
            continue
        kept.append(e)
    return np.stack(kept, axis=0) if kept else embs[:0]

def db_delete_embeddings_for_person(conn, *, trusted_id: int, model_name: str) -> int:
    cur = conn.execute(
        """
        DELETE FROM trusted_person_embedding
        WHERE trusted_id = ?
          AND embedding_type = 'face'
          AND model_name = ?
        """,
        (trusted_id, model_name),
    )
    return cur.rowcount or 0



def iter_images(folder: Path) -> list[Path]:
    files = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            files.append(p)
    return files

def pick_single_good_face(
    app: FaceAnalysis,
    img_bgr: np.ndarray,
    *,
    min_score: float = 0.6,
    min_px: int = 80,
) -> Tuple[Optional[np.ndarray], str]:
    """
    Returns (embedding, reason). If embedding is None, reason is why we skipped.
    Enforces: exactly one "good" face.
    """
    faces = app.get(img_bgr) or []
    good = []

    for f in faces:
        score = float(getattr(f, "det_score", 1.0))
        # bbox is [x1,y1,x2,y2]
        x1, y1, x2, y2 = [int(v) for v in f.bbox]
        w, h = (x2 - x1), (y2 - y1)

        if score < min_score:
            continue
        if w < min_px or h < min_px:
            continue

        emb = l2_normalize(f.embedding.astype("float32"))
        good.append((emb, score, (w * h)))

    if len(good) == 0:
        return None, "no_good_face"
    if len(good) > 1:
        return None, "multiple_good_faces"

    return good[0][0], "ok"

# ---------- Commands ----------
def cmd_list(_args):
    conn = get_conn()
    try:
        rows = conn.execute("SELECT trusted_id, name FROM trusted_person ORDER BY trusted_id").fetchall()
        for r in rows:
            print(f"{int(r[0])}\t{r[1] or ''}")
    finally:
        conn.close()


def cmd_add(args):
    conn = get_conn()
    tid = db_add_trusted_person(conn, args.name)
    print(f"created trusted_id={tid} name={args.name!r}")

def cmd_enroll_face(args):
    p = Path(args.image).resolve()
    img = cv2.imread(str(p))
    if img is None:
        raise RuntimeError(f"could not read image: {p}")

    app = FaceAnalysis(name=args.model)
    app.prepare(ctx_id=-1, det_size=(640, 640))
    model_name = f"insightface:{args.model}"

    emb, reason = pick_single_good_face(app, img)

    if emb is None:
        print(f"No suitable face found: {reason}")
        return

    # For the single-image enroll command, store the face embedding
    conn = get_conn()
    db_insert_embedding(
        conn,
        trusted_id=args.trusted_id,
        embedding_type="face",
        model_name=model_name,
        emb=emb,
        camera_id=args.camera_id,
        quality_score=1.0,
    )
    conn.commit()
    conn.close()

    print(f"stored 1 face embedding for trusted_id={args.trusted_id} model={model_name}")

def main():
    ap = argparse.ArgumentParser(prog="trusted")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("list")
    p.set_defaults(func=cmd_list)

    p = sp.add_parser("add")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_add)

    p = sp.add_parser("enroll-face")
    p.add_argument("--trusted-id", type=int, required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--model", default="buffalo_l")
    p.add_argument("--prototypes", type=int, default=8)
    p.add_argument("--camera-id", type=int, default=None)
    p.set_defaults(func=cmd_enroll_face)
    p = sp.add_parser("scan-folders")
    p.add_argument("--root", default="data/trusted_faces")
    p.add_argument("--model", default="buffalo_l")
    p.add_argument("--prototypes", type=int, default=8)
    p.add_argument("--min-faces", type=int, default=3, help="minimum # of single-face images required to build a profile")
    p.add_argument("--min-score", type=float, default=0.6)
    p.add_argument("--min-px", type=int, default=80)
    p.add_argument("--camera-id", type=int, default=None)
    p.add_argument("--rebuild", action="store_true", help="delete existing face embeddings for this person/model and reinsert")
    p.add_argument("--dedupe", action="store_true", help="remove near-duplicate embeddings before clustering")
    p.add_argument("--dedupe-threshold", type=float, default=0.995)
    p.set_defaults(func=scan_trusted_faces)
    

    args = ap.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()

import time
import sqlite3
from dataclasses import dataclass
from typing import Dict, Optional

from apps.orchestrator.event import Event  # your existing Event


@dataclass
class SubjectState:
    """Tracks how long a given 'subject' (scene) has been present."""
    first_seen: float
    last_seen: float
    alert_sent: bool = False


@dataclass
class SceneSummary:
    """Last known scene for nicer, 'delta-aware' messages."""
    num_vehicles: int
    num_people: int
    last_update_ts: float


class BehaviorManager:
    """
    Manages scene-level behavior:
    - Enforces 'must persist for min_persist' before alerting
    - Suppresses repeated alerts for the same subject within alert_cooldown
    - Generates human-friendly messages based on change in scene
    """

    def __init__(
        self,
        db_path: str,
        min_persist: float = 2.0,      # seconds subject must persist before alert
        alert_cooldown: float = 60.0,  # seconds before re-alerting on same subject
    ):
        self.db_path = db_path
        self.min_persist = min_persist
        self.alert_cooldown = alert_cooldown

        # subject_key -> SubjectState
        self.subjects: Dict[str, SubjectState] = {}

        # last scene we alerted on (for “another car arrived” style phrasing)
        self.last_scene: Optional[SceneSummary] = None

        self._ensure_tables()

    # ---------- DB setup ----------

    def _ensure_tables(self) -> None:
        """Create alerts table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_key   TEXT NOT NULL,
                    first_seen    REAL NOT NULL,
                    last_alert_ts REAL NOT NULL
                )
                """
            )
            conn.commit()

    # ---------- Helpers to understand the scene ----------

    def _extract_counts(self, evt: Event) -> tuple[int, int]:
        """
        Get num_vehicles / num_people from the event.
        - Preferred: evt.payload["num_vehicles"], evt.payload["num_people"]
        - Fallback: heuristics from evt.kind
        """
        num_vehicles = 0
        num_people = 0

        if evt.payload:
            num_vehicles = int(evt.payload.get("num_vehicles", 0))
            num_people = int(evt.payload.get("num_people", 0))

        # Fallback if payload isn't populated yet
        if num_vehicles == 0 and evt.kind == "vehicle":
            num_vehicles = 1
        if num_people == 0 and evt.kind == "person":
            num_people = 1

        return num_vehicles, num_people

    def _subject_key(self, evt: Event, num_vehicles: int, num_people: int) -> str:
        """
        Build a key that roughly identifies 'the same situation'.
        This is what we use to decide 'have we already alerted about this?'.
        You can enrich this later with color, carrier, etc.
        """
        return f"{evt.source}:{evt.type}:veh={num_vehicles}:ppl={num_people}"

    # ---------- DB alert history ----------

    def _recent_alert_exists(self, subject_key: str, now: float) -> bool:
        """Return True if we alerted on this subject_key within alert_cooldown."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT last_alert_ts
                FROM alerts
                WHERE subject_key = ?
                ORDER BY last_alert_ts DESC
                LIMIT 1
                """,
                (subject_key,),
            ).fetchone()

        if not row:
            return False

        last_alert_ts = float(row[0])
        return (now - last_alert_ts) < self.alert_cooldown

    def _record_alert(self, subject_key: str, first_seen: float, now: float) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO alerts (subject_key, first_seen, last_alert_ts)
                VALUES (?, ?, ?)
                """,
                (subject_key, first_seen, now),
            )
            conn.commit()

    # ---------- Main entrypoint ----------

    def execute(self, evt: Event) -> dict:
        """
        Decide whether to alert on this event.

        Returns a dict like:
        - {"status": "pending",   "action": "none"}
        - {"status": "suppressed","action": "none"}
        - {"status": "alert",     "action": "speak", "message": "...", "subject_key": ...}
        """
        now = time.time()

        # 1) Understand scene composition
        num_vehicles, num_people = self._extract_counts(evt)
        subject_key = self._subject_key(evt, num_vehicles, num_people)

        # 2) Track persistence in memory
        state = self.subjects.get(subject_key)
        if state is None:
            state = SubjectState(first_seen=now, last_seen=now)
            self.subjects[subject_key] = state
        else:
            state.last_seen = now

        # 3) Require that the scene persists for min_persist seconds
        if (now - state.first_seen) < self.min_persist:
            return {"status": "pending", "action": "none"}

        # 4) If we've already alerted about this subject recently, suppress
        if self._recent_alert_exists(subject_key, now):
            state.alert_sent = True
            return {"status": "suppressed", "action": "none"}

        # 5) New or stale subject: record alert and generate a message
        self._record_alert(subject_key, state.first_seen, now)
        state.alert_sent = True

        # 6) Build a human-friendly message based on *change*
        msg = self._build_scene_message(evt, num_vehicles, num_people, now)

        return {
            "status": "alert",
            "action": "speak",  # your orchestrator can map this to TTS, push, etc.
            "message": msg,
            "subject_key": subject_key,
        }

    # ---------- Message generation based on change in scene ----------

    def _build_scene_message(
        self,
        evt: Event,
        num_vehicles: int,
        num_people: int,
        now: float,
    ) -> str:
        """Generate a human-friendly message using last_scene for context."""
        prev = self.last_scene

        # Default message
        msg = "Activity detected."

        if evt.source == "driveway":
            # driveway-specific phrasing
            if prev is None or prev.num_vehicles == 0:
                if num_vehicles >= 1:
                    msg = "A vehicle has arrived in the driveway."
                elif num_people >= 1:
                    msg = "Someone is in the driveway."
            else:
                # there was already at least one vehicle/person
                if num_vehicles > prev.num_vehicles:
                    msg = (
                        f"Another vehicle has arrived. "
                        f"There are now {num_vehicles} vehicles in the driveway."
                    )
                elif num_people > prev.num_people:
                    msg = (
                        f"Another person has entered the driveway. "
                        f"There are now {num_people} people in view."
                    )
                else:
                    msg = "There is ongoing activity in the driveway."
        elif evt.source == "doorbell":
            # doorbell-specific phrasing
            if num_people >= 1:
                msg = "Someone is at the door."
            elif num_vehicles >= 1:
                msg = "A vehicle has pulled up by the door."

        # Update last_scene snapshot
        self.last_scene = SceneSummary(
            num_vehicles=num_vehicles,
            num_people=num_people,
            last_update_ts=now,
        )

        return msg


# ---------- Simple manual test ----------

if __name__ == "__main__":
    # Minimal fake Event for testing
    e = Event(
        source="driveway",
        type="approach",
        kind="vehicle",
        snapshot="/tmp/fake.jpg",
        payload={"num_vehicles": 1, "num_people": 0},
    )

    mgr = BehaviorManager(db_path="behavior_test.db")

    # First call: should be 'pending' until min_persist has passed
    print("First execute:", mgr.execute(e))

    time.sleep(2.1)
    # Second call: now past min_persist, should alert
    print("Second execute:", mgr.execute(e))

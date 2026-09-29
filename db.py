import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any
import re

from contextlib import contextmanager

DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(__file__))
DB_PATH = os.path.join(DATA_DIR, "Yukti.db")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                created_at TEXT NOT NULL,
                text TEXT NOT NULL,
                data TEXT NOT NULL,
                user_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER REFERENCES users(id)")
        except sqlite3.OperationalError:
            pass


        conn.execute(
    """
    CREATE TABLE IF NOT EXISTS metacognitive_checkins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        concept TEXT NOT NULL,
        confidence_rating INTEGER NOT NULL,
        reflection TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
    )
    """
)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS progress (
                session_id TEXT PRIMARY KEY,
                quiz_attempts INTEGER DEFAULT 0,
                quiz_score_total INTEGER DEFAULT 0,
                flashcards_total INTEGER DEFAULT 0,
                flashcards_mastered INTEGER DEFAULT 0,
                updated_at TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learner_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                concept TEXT NOT NULL,
                mastery REAL DEFAULT 0.0,
                confidence REAL DEFAULT 0.5,
                attempts INTEGER DEFAULT 0,
                correct_attempts INTEGER DEFAULT 0,
                recent_score REAL DEFAULT 0.0,
                needs_examples INTEGER DEFAULT 0,
                needs_step_by_step INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL,
                last_reviewed_at TEXT,
                next_review_at TEXT,
                review_interval_days REAL DEFAULT 1.0,
                UNIQUE(session_id, concept),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS card_schedule (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                front TEXT NOT NULL,
                easiness REAL DEFAULT 2.5,
                interval INTEGER DEFAULT 1,
                repetitions INTEGER DEFAULT 0,
                next_review TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learner_profiles (
                session_id TEXT PRIMARY KEY,
                learning_style TEXT DEFAULT 'adaptive',
                preferred_difficulty TEXT DEFAULT 'medium',
                strengths TEXT DEFAULT '[]',
                weaknesses TEXT DEFAULT '[]',
                updated_at TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
            """
        )        

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS misconceptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                concept TEXT NOT NULL,
                misconception TEXT NOT NULL,
                evidence TEXT,
                severity TEXT NOT NULL DEFAULT 'medium',
                suggested_intervention TEXT,
                occurrences INTEGER NOT NULL DEFAULT 1,
                resolved INTEGER NOT NULL DEFAULT 0,
                first_detected TEXT NOT NULL,
                last_detected TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
            """
        )

def _normalise_session(data: dict[str, Any]) -> dict[str, Any]:
    session_id = data.get("id") or data.get("session_id")
    title = data.get("title") or data.get("filename") or "Untitled"
    created_at = data.get("created_at") or datetime.utcnow().isoformat()
    full_text = data.get("full_text") or data.get("text") or ""
    data["id"] = session_id
    data["session_id"] = session_id
    data["title"] = title
    data["filename"] = data.get("filename") or data.get("original_filename") or title
    data["original_filename"] = data.get("original_filename") or data["filename"]
    data["created_at"] = created_at
    data["full_text"] = full_text
    data["text"] = full_text
    return data


def save_session_data(session_id: str, data: dict[str, Any], user_id: int | None = None):
    data = _normalise_session(dict(data))
    with get_conn() as conn:
        # Get existing user_id if any, so we don't overwrite it with NULL on replace
        existing = conn.execute("SELECT user_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        final_user_id = user_id
        if existing and existing["user_id"] is not None:
            final_user_id = existing["user_id"]
            
        conn.execute(
            """
            INSERT OR REPLACE INTO sessions (session_id, filename, created_at, text, data, user_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                data["filename"],
                data["created_at"],
                data["full_text"],
                json.dumps(data),
                final_user_id
            ),
        )

def get_session_data(session_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["data"])
    except Exception:
        data = {}
    data.setdefault("id", row["session_id"])
    data.setdefault("session_id", row["session_id"])
    data.setdefault("title", row["filename"])
    data.setdefault("filename", row["filename"])
    data.setdefault("original_filename", row["filename"])
    data.setdefault("created_at", row["created_at"])
    data.setdefault("full_text", row["text"])
    data.setdefault("text", row["text"])
    return data


def list_session_data(user_id: int | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        if user_id is not None:
            rows = conn.execute(
                "SELECT session_id FROM sessions WHERE user_id=? ORDER BY created_at DESC", (user_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT session_id FROM sessions ORDER BY created_at DESC"
            ).fetchall()
    return [data for row in rows if (data := get_session_data(row["session_id"]))]


def delete_session_data(session_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM progress WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM card_schedule WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM misconceptions WHERE session_id=?",(session_id,),
)        


def save_message(session_id: str, role: str, content: str, created_at: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, created_at),
        )


def get_history(session_id: str, limit: int = 6) -> list[dict[str, str]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT role, content FROM messages
            WHERE session_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    return list(reversed([dict(row) for row in rows]))


def record_quiz_score(session_id: str, score: int | float):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO progress (session_id, quiz_attempts, quiz_score_total, updated_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                quiz_attempts = quiz_attempts + 1,
                quiz_score_total = quiz_score_total + excluded.quiz_score_total,
                updated_at = excluded.updated_at
            """,
            (session_id, score, now),
        )

def update_learner_state(
    session_id: str,
    correct_concepts: list[str],
    missed_concepts: list[str],
    score: float,
    misconception_severity: str | None = None,
):
    now = datetime.utcnow()

    with get_conn() as conn:

        # =========================================================
        # CORRECT CONCEPTS
        # =========================================================
        for concept in correct_concepts:

            row = conn.execute(
                """
                SELECT
                    mastery,
                    confidence,
                    attempts,
                    correct_attempts,
                    review_interval_days
                FROM learner_state
                WHERE session_id=? AND concept=?
                """,
                (session_id, concept),
            ).fetchone()

            if row:
                attempts = row["attempts"] + 1
                correct_attempts = row["correct_attempts"] + 1

                mastery = (
                    correct_attempts / attempts * 100
                    if attempts > 0
                    else 0.0
                )

                confidence = min(
                    1.0,
                    row["confidence"] + 0.1
                )

                # Increase revision interval after successful recall.
                previous_interval = row["review_interval_days"] or 1.0

                review_interval = min(
                    30.0,
                    max(1.0, previous_interval * 2)
                )

                next_review = now + timedelta(
                    days=review_interval
                )

                conn.execute(
                    """
                    UPDATE learner_state
                    SET mastery=?,
                        confidence=?,
                        attempts=?,
                        correct_attempts=?,
                        recent_score=?,
                        needs_examples=0,
                        needs_step_by_step=0,
                        last_reviewed_at=?,
                        next_review_at=?,
                        review_interval_days=?,
                        updated_at=?
                    WHERE session_id=? AND concept=?
                    """,
                    (
                        mastery,
                        confidence,
                        attempts,
                        correct_attempts,
                        score,
                        now.isoformat(),
                        next_review.isoformat(),
                        review_interval,
                        now.isoformat(),
                        session_id,
                        concept,
                    ),
                )

            else:
                # First successful demonstration.
                review_interval = 1.0

                next_review = now + timedelta(
                    days=review_interval
                )

                conn.execute(
                    """
                    INSERT INTO learner_state (
                        session_id,
                        concept,
                        mastery,
                        confidence,
                        attempts,
                        correct_attempts,
                        recent_score,
                        needs_examples,
                        needs_step_by_step,
                        updated_at,
                        last_reviewed_at,
                        next_review_at,
                        review_interval_days
                    )
                    VALUES (
                        ?,
                        ?,
                        100.0,
                        0.6,
                        1,
                        1,
                        ?,
                        0,
                        0,
                        ?,
                        ?,
                        ?,
                        ?
                    )
                    """,
                    (
                        session_id,
                        concept,
                        score,
                        now.isoformat(),
                        now.isoformat(),
                        next_review.isoformat(),
                        review_interval,
                    ),
                )

        # =========================================================
        # MISSED CONCEPTS
        # =========================================================
        for concept in missed_concepts:

            row = conn.execute(
                """
                SELECT
                    mastery,
                    confidence,
                    attempts,
                    correct_attempts
                FROM learner_state
                WHERE session_id=? AND concept=?
                """,
                (session_id, concept),
            ).fetchone()

            # A missed concept should be reviewed soon.
            review_interval = 1.0
            next_review = now + timedelta(
                days=review_interval
            )

            confidence_drop = {
                "low": 0.05,
                "medium": 0.10,
                "high": 0.15,
            }.get(
                misconception_severity,
                0.10
            )

            if row:

                attempts = row["attempts"] + 1
                correct_attempts = row["correct_attempts"]

                mastery = (
                    correct_attempts / attempts * 100
                    if attempts > 0
                    else 0.0
                )

                confidence = max(
                    0.0,
                    row["confidence"] - confidence_drop
                )

                conn.execute(
                    """
                    UPDATE learner_state
                    SET mastery=?,
                        confidence=?,
                        attempts=?,
                        recent_score=?,
                        needs_examples=1,
                        needs_step_by_step=1,
                        last_reviewed_at=?,
                        next_review_at=?,
                        review_interval_days=?,
                        updated_at=?
                    WHERE session_id=? AND concept=?
                    """,
                    (
                        mastery,
                        confidence,
                        attempts,
                        score,
                        now.isoformat(),
                        next_review.isoformat(),
                        review_interval,
                        now.isoformat(),
                        session_id,
                        concept,
                    ),
                )

            else:

                initial_confidence = {
                    "low": 0.45,
                    "medium": 0.40,
                    "high": 0.35,
                }.get(
                    misconception_severity,
                    0.40
                )

                conn.execute(
                    """
                    INSERT INTO learner_state (
                        session_id,
                        concept,
                        mastery,
                        confidence,
                        attempts,
                        correct_attempts,
                        recent_score,
                        needs_examples,
                        needs_step_by_step,
                        updated_at,
                        last_reviewed_at,
                        next_review_at,
                        review_interval_days
                    )
                    VALUES (
                        ?,
                        ?,
                        0.0,
                        ?,
                        1,
                        0,
                        ?,
                        1,
                        1,
                        ?,
                        ?,
                        ?,
                        ?
                    )
                    """,
                    (
                        session_id,
                        concept,
                        initial_confidence,
                        score,
                        now.isoformat(),
                        now.isoformat(),
                        next_review.isoformat(),
                        review_interval,
                    ),
                )

def normalize_misconception(text: str | None) -> str:
    if not text:
        return ""

    text = text.lower().strip()

    # Normalize formatting
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    # Remove common filler phrases
    filler_phrases = [
        "the student",
        "the learner",
        "student",
        "learner",
        "seems to",
        "appears to",
        "shows a misunderstanding of",
        "shows misunderstanding of",
        "has a misconception about",
        "has a misunderstanding about",
        "misunderstands",
    ]

    for phrase in filler_phrases:
        text = text.replace(phrase, " ")

    text = re.sub(r"\s+", " ", text).strip()

    return text

def record_misconception(
    session_id: str,
    concept: str,
    severity: str,
    misconception: str | None = None,
    evidence: str | None = None,
    suggested_intervention: str | None = None,
):
    """
    Persist a detected misconception without modifying learner mastery.

    Mastery and confidence are updated centrally by
    update_learner_state(). This function is responsible only for
    misconception memory and recurrence tracking.
    """

    now = datetime.utcnow().isoformat()

    with get_conn() as conn:

        # ---------------------------------------------------------
        # Persist / update misconception history
        # ---------------------------------------------------------
        existing = None

        if misconception:
            existing = conn.execute(
                """
                SELECT id, occurrences
                FROM misconceptions
                WHERE session_id=?
                  AND LOWER(concept)=LOWER(?)
                  AND LOWER(misconception)=LOWER(?)
                  AND resolved=0
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    session_id,
                    concept,
                    misconception,
                ),
            ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE misconceptions
                SET occurrences=?,
                    severity=?,
                    evidence=?,
                    suggested_intervention=?,
                    last_detected=?,
                    resolved=0
                WHERE id=?
                """,
                (
                    existing["occurrences"] + 1,
                    severity,
                    evidence,
                    suggested_intervention,
                    now,
                    existing["id"],
                ),
            )

        else:
            conn.execute(
                """
                INSERT INTO misconceptions (
                    session_id,
                    concept,
                    misconception,
                    evidence,
                    severity,
                    suggested_intervention,
                    occurrences,
                    resolved,
                    first_detected,
                    last_detected
                )
                VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
                """,
                (
                    session_id,
                    concept,
                    misconception or "unspecified_misconception",
                    evidence,
                    severity,
                    suggested_intervention,
                    now,
                    now,
                ),
            )

def get_active_misconceptions(
    session_id: str,
    concept: str | None = None,
) -> list[dict]:
    """
    Return unresolved misconceptions for a learner.
    """

    with get_conn() as conn:
        if concept:
            rows = conn.execute(
                """
                SELECT *
                FROM misconceptions
                WHERE session_id=?
                  AND LOWER(concept)=LOWER(?)
                  AND resolved=0
                ORDER BY occurrences DESC, last_detected DESC
                """,
                (session_id, concept),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM misconceptions
                WHERE session_id=?
                  AND resolved=0
                ORDER BY occurrences DESC, last_detected DESC
                """,
                (session_id,),
            ).fetchall()

    return [dict(row) for row in rows]


def resolve_misconceptions(
    session_id: str,
    concept: str,
    misconception_text: str | None = None,
):
    """
    Mark active misconceptions for a concept as resolved
    after successful reassessment.
    """

    with get_conn() as conn:
        if misconception_text:
            conn.execute(
                """
                UPDATE misconceptions
                SET resolved=1
                WHERE session_id=?
                  AND LOWER(concept)=LOWER(?)
                  AND LOWER(misconception)=LOWER(?)
                  AND resolved=0
                """,
                (session_id, concept, misconception_text),
            )
        else:
            conn.execute(
                """
                UPDATE misconceptions
                SET resolved=1
                WHERE session_id=?
                  AND LOWER(concept)=LOWER(?)
                  AND resolved=0
                """,
                (session_id, concept),
            )

def get_learner_state(session_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                concept,
                mastery,
                confidence,
                attempts,
                correct_attempts,
                recent_score,
                needs_examples,
                needs_step_by_step,
                updated_at,
                last_reviewed_at,
                next_review_at,
                review_interval_days
            FROM learner_state
            WHERE session_id=?
            ORDER BY mastery ASC
            """,
            (session_id,),
        ).fetchall()

    return [dict(row) for row in rows]

def record_metacognitive_checkin(
    session_id: str,
    concept: str,
    confidence_rating: int,
    reflection: str | None = None,
):
    now = datetime.utcnow().isoformat()

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO metacognitive_checkins (
                session_id,
                concept,
                confidence_rating,
                reflection,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                concept,
                confidence_rating,
                reflection,
                now,
            ),
        )

def get_latest_metacognitive_checkin(
    session_id: str,
    concept: str,
    
):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT confidence_rating
            FROM metacognitive_checkins
            WHERE session_id = ? AND LOWER(concept) = LOWER(?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id, concept),
        ).fetchone()

    return row["confidence_rating"] if row else None

def upsert_flashcard_progress(session_id: str, total: int, mastered: int):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO progress (session_id, flashcards_total, flashcards_mastered, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                flashcards_total = excluded.flashcards_total,
                flashcards_mastered = excluded.flashcards_mastered,
                updated_at = excluded.updated_at
            """,
            (session_id, total, mastered, now),
        )


def get_progress(session_id: str) -> dict[str, float | int]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM progress WHERE session_id=?",
            (session_id,),
        ).fetchone()
    if not row:
        return {"quiz_avg": 0, "mastery_pct": 0}
    quiz_avg = row["quiz_score_total"] / max(row["quiz_attempts"], 1)
    mastery_pct = row["flashcards_mastered"] / max(row["flashcards_total"], 1) * 100
    return {"quiz_avg": round(quiz_avg, 1), "mastery_pct": round(mastery_pct)}


def upsert_card_schedule(session_id: str, card_id: str, front: str, next_review: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO card_schedule (id, session_id, front, next_review)
            VALUES (?, ?, ?, ?)
            """,
            (card_id, session_id, front, next_review),
        )


def get_card_schedule(card_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM card_schedule WHERE id=?",
            (card_id,),
        ).fetchone()


def update_card_schedule(card_id: str, easiness: float, interval: int, repetitions: int, next_review: str):
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE card_schedule
            SET easiness=?, interval=?, repetitions=?, next_review=?
            WHERE id=?
            """,
            (easiness, interval, repetitions, next_review, card_id),
        )


def get_due_card_ids(session_id: str) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id FROM card_schedule
            WHERE session_id=?
            ORDER BY
                CASE WHEN next_review <= datetime('now') THEN 0 ELSE 1 END,
                next_review ASC
            """,
            (session_id,),
        ).fetchall()
    return [row["id"] for row in rows]

def get_learning_analytics(session_id: str) -> dict:
    """
    Return an adaptive-learning summary for a learner session.
    """

    with get_conn() as conn:
        states = conn.execute(
            """
            SELECT
                concept,
                mastery,
                confidence,
                attempts,
                correct_attempts,
                recent_score,
                needs_examples,
                needs_step_by_step,
                updated_at,
                last_reviewed_at,
                next_review_at,
                review_interval_days
            FROM learner_state
            WHERE session_id=?
            ORDER BY mastery DESC
            """,
            (session_id,),
        ).fetchall()

    state_list = [dict(row) for row in states]

    total_concepts = len(state_list)

    average_mastery = (
        sum(item["mastery"] for item in state_list)
        / total_concepts
        if total_concepts
        else 0.0
    )

    mastered_concepts = [
        item
        for item in state_list
        if item["mastery"] >= 70
    ]

    weak_concepts = [
        item
        for item in state_list
        if item["mastery"] < 70
    ]

    due_reviews = [
        item
        for item in state_list
        if item.get("next_review_at")
        and item["next_review_at"] <= datetime.utcnow().isoformat()
    ]

    misconceptions = get_active_misconceptions(session_id)

    return {
        "overall_mastery": round(average_mastery, 2),
        "total_concepts": total_concepts,
        "mastered_concepts": len(mastered_concepts),
        "weak_concepts": len(weak_concepts),
        "due_reviews": len(due_reviews),
        "active_misconceptions": len(misconceptions),
        "average_confidence": round(
            (
                sum(item["confidence"] for item in state_list)
                / total_concepts
            )
            if total_concepts
            else 0.0,
            2,
        ),
        "concepts": state_list,
        "weak_concept_details": weak_concepts,
        "due_review_details": due_reviews,
        "misconceptions": misconceptions,
    }

def get_cumulative_learning_analytics(user_id: int) -> dict:
    """
    Return a cumulative adaptive-learning summary across all sessions for a user.
    """
    with get_conn() as conn:
        states = conn.execute(
            """
            SELECT
                ls.concept,
                AVG(ls.mastery) as mastery,
                AVG(ls.confidence) as confidence,
                SUM(ls.attempts) as attempts,
                SUM(ls.correct_attempts) as correct_attempts,
                AVG(ls.recent_score) as recent_score,
                SUM(ls.needs_examples) as needs_examples,
                SUM(ls.needs_step_by_step) as needs_step_by_step,
                MAX(ls.updated_at) as updated_at,
                MAX(ls.last_reviewed_at) as last_reviewed_at,
                MIN(ls.next_review_at) as next_review_at,
                AVG(ls.review_interval_days) as review_interval_days
            FROM learner_state ls
            JOIN sessions s ON ls.session_id = s.session_id
            WHERE s.user_id = ?
            GROUP BY ls.concept
            ORDER BY mastery DESC
            """,
            (user_id,),
        ).fetchall()

    state_list = [dict(row) for row in states]
    total_concepts = len(state_list)
    average_mastery = (
        sum(item["mastery"] for item in state_list) / total_concepts
        if total_concepts
        else 0.0
    )
    average_confidence = (
        sum(item["confidence"] for item in state_list) / total_concepts
        if total_concepts
        else 0.5
    )

    mastered_concepts = [item for item in state_list if item["mastery"] >= 70]
    weak_concepts = [item for item in state_list if item["mastery"] < 70]
    
    import datetime
    now_iso = datetime.datetime.utcnow().isoformat()
    due_reviews = [
        item for item in state_list
        if item["next_review_at"] and item["next_review_at"] <= now_iso
    ]

    with get_conn() as conn:
        misc = conn.execute(
            """
            SELECT
                m.id,
                m.concept,
                m.misconception,
                m.severity,
                SUM(m.occurrences) as occurrences,
                MAX(m.resolved) as resolved,
                m.suggested_intervention
            FROM misconceptions m
            JOIN sessions s ON m.session_id = s.session_id
            WHERE s.user_id = ?
            GROUP BY m.concept, m.misconception
            ORDER BY occurrences DESC
            """,
            (user_id,),
        ).fetchall()

    misc_list = [dict(row) for row in misc]
    active_misc = [m for m in misc_list if not m["resolved"]]
    resolved_misc = [m for m in misc_list if m["resolved"]]

    return {
        "overall_mastery": average_mastery,
        "average_confidence": average_confidence,
        "total_concepts": total_concepts,
        "mastered_concepts": len(mastered_concepts),
        "weak_concepts": len(weak_concepts),
        "due_reviews": len(due_reviews),
        "active_misconceptions": len(active_misc),
        "resolved_misconceptions": len(resolved_misc),
        "concepts": state_list,
        "weak_concept_details": [
            {
                "concept": c["concept"],
                "mastery": c["mastery"],
                "confidence": c["confidence"]
            }
            for c in weak_concepts
        ],
        "due_review_details": [
            {
                "concept": c["concept"],
                "mastery": c["mastery"],
                "confidence": c["confidence"],
                "next_review_at": c["next_review_at"]
            }
            for c in due_reviews
        ],
        "misconceptions": active_misc,
        "resolved_misconceptions_list": resolved_misc,
    }

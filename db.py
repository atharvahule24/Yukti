import json
import os
import re
from datetime import datetime, timedelta
from typing import Any

from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def init_db():
    pass

def get_conn():
    from contextlib import contextmanager
    @contextmanager
    def mock_conn():
        yield None
    return mock_conn()

def _normalise_session(data: dict[str, Any]) -> dict[str, Any]:
    session_id = data.get("id") or data.get("session_id")
    title = data.get("title") or data.get("filename") or "Untitled"
    created_at = data.get("created_at") or datetime.utcnow().isoformat()
    full_text = data.get("full_text") or data.get("text") or data.get("content") or ""
    data["id"] = session_id
    data["session_id"] = session_id
    data["title"] = title
    data["filename"] = data.get("filename") or data.get("original_filename") or title
    data["original_filename"] = data.get("original_filename") or data["filename"]
    data["created_at"] = created_at
    data["full_text"] = full_text
    data["text"] = full_text
    data["content"] = full_text
    return data

def save_session_data(session_id: str, data: dict[str, Any], user_id: int | None = None):
    data = _normalise_session(dict(data))
    
    # Get existing user_id if any, so we don't overwrite it with NULL on replace
    res = supabase.table("sessions").select("user_id").eq("session_id", session_id).execute()
    existing_user_id = res.data[0]["user_id"] if res.data and res.data[0].get("user_id") is not None else None
    
    final_user_id = user_id if user_id is not None else existing_user_id
    
    row = {
        "session_id": session_id,
        "filename": data["filename"],
        "created_at": data["created_at"],
        "text": data["full_text"],
        "data": json.dumps(data),
        "user_id": final_user_id
    }
    supabase.table("sessions").upsert(row).execute()

def get_session_data(session_id: str) -> dict[str, Any] | None:
    res = supabase.table("sessions").select("*").eq("session_id", session_id).limit(1).execute()
    res.data = res.data[0] if res.data else None
    if not res.data:
        return None
    row = res.data
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

    full_text = data.get("full_text") or data.get("text") or data.get("content") or row.get("text") or ""
    data["full_text"] = full_text
    data["text"] = full_text
    data["content"] = full_text
    return data

def list_session_data(user_id: int | None = None) -> list[dict[str, Any]]:
    query = supabase.table("sessions").select("session_id").order("created_at", desc=True)
    if user_id is not None:
        query = query.eq("user_id", user_id)
    res = query.execute()
    return [data for row in res.data if (data := get_session_data(row["session_id"]))]

def delete_session_data(session_id: str):
    # PostgreSQL ON DELETE CASCADE handles related tables (messages, progress, etc.)
    supabase.table("sessions").delete().eq("session_id", session_id).execute()

def save_message(session_id: str, role: str, content: str, created_at: str):
    supabase.table("messages").insert({
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": created_at
    }).execute()

def get_history(session_id: str, limit: int = 6) -> list[dict[str, str]]:
    res = supabase.table("messages").select("role, content").eq("session_id", session_id).order("id", desc=True).limit(limit).execute()
    return list(reversed(res.data))

def record_quiz_score(session_id: str, score: int | float):
    now = datetime.utcnow().isoformat()
    res = supabase.table("progress").select("*").eq("session_id", session_id).limit(1).execute()
    res.data = res.data[0] if res.data else None
    if res.data:
        new_attempts = (res.data.get("quiz_attempts") or 0) + 1
        new_score = (res.data.get("quiz_score_total") or 0) + score
        supabase.table("progress").update({
            "quiz_attempts": new_attempts,
            "quiz_score_total": new_score,
            "updated_at": now
        }).eq("session_id", session_id).execute()
    else:
        supabase.table("progress").insert({
            "session_id": session_id,
            "quiz_attempts": 1,
            "quiz_score_total": score,
            "updated_at": now
        }).execute()

def update_learner_state(
    session_id: str,
    correct_concepts: list[str],
    missed_concepts: list[str],
    score: float,
    misconception_severity: str | None = None,
):
    now = datetime.utcnow()
    
    for concept in correct_concepts:
        res = supabase.table("learner_state").select("*").eq("session_id", session_id).eq("concept", concept).limit(1).execute()
        res.data = res.data[0] if res.data else None
        row = res.data
        if row:
            attempts = row.get("attempts", 0) + 1
            correct_attempts = row.get("correct_attempts", 0) + 1
            mastery = (correct_attempts / attempts * 100) if attempts > 0 else 0.0
            confidence = min(1.0, row.get("confidence", 0.5) + 0.1)
            previous_interval = row.get("review_interval_days") or 1.0
            review_interval = min(30.0, max(1.0, previous_interval * 2))
            next_review = now + timedelta(days=review_interval)
            
            supabase.table("learner_state").update({
                "mastery": mastery,
                "confidence": confidence,
                "attempts": attempts,
                "correct_attempts": correct_attempts,
                "recent_score": score,
                "needs_examples": 0,
                "needs_step_by_step": 0,
                "last_reviewed_at": now.isoformat(),
                "next_review_at": next_review.isoformat(),
                "review_interval_days": review_interval,
                "updated_at": now.isoformat()
            }).eq("session_id", session_id).eq("concept", concept).execute()
        else:
            review_interval = 1.0
            next_review = now + timedelta(days=review_interval)
            supabase.table("learner_state").insert({
                "session_id": session_id,
                "concept": concept,
                "mastery": 100.0,
                "confidence": 0.6,
                "attempts": 1,
                "correct_attempts": 1,
                "recent_score": score,
                "needs_examples": 0,
                "needs_step_by_step": 0,
                "updated_at": now.isoformat(),
                "last_reviewed_at": now.isoformat(),
                "next_review_at": next_review.isoformat(),
                "review_interval_days": review_interval
            }).execute()

    for concept in missed_concepts:
        res = supabase.table("learner_state").select("*").eq("session_id", session_id).eq("concept", concept).limit(1).execute()
        res.data = res.data[0] if res.data else None
        row = res.data
        
        review_interval = 1.0
        next_review = now + timedelta(days=review_interval)
        confidence_drop = {"low": 0.05, "medium": 0.10, "high": 0.15}.get(misconception_severity, 0.10)
        
        if row:
            attempts = row.get("attempts", 0) + 1
            correct_attempts = row.get("correct_attempts", 0)
            mastery = (correct_attempts / attempts * 100) if attempts > 0 else 0.0
            confidence = max(0.0, row.get("confidence", 0.5) - confidence_drop)
            
            supabase.table("learner_state").update({
                "mastery": mastery,
                "confidence": confidence,
                "attempts": attempts,
                "recent_score": score,
                "needs_examples": 1,
                "needs_step_by_step": 1,
                "last_reviewed_at": now.isoformat(),
                "next_review_at": next_review.isoformat(),
                "review_interval_days": review_interval,
                "updated_at": now.isoformat()
            }).eq("session_id", session_id).eq("concept", concept).execute()
        else:
            initial_confidence = {"low": 0.45, "medium": 0.40, "high": 0.35}.get(misconception_severity, 0.40)
            supabase.table("learner_state").insert({
                "session_id": session_id,
                "concept": concept,
                "mastery": 0.0,
                "confidence": initial_confidence,
                "attempts": 1,
                "correct_attempts": 0,
                "recent_score": score,
                "needs_examples": 1,
                "needs_step_by_step": 1,
                "updated_at": now.isoformat(),
                "last_reviewed_at": now.isoformat(),
                "next_review_at": next_review.isoformat(),
                "review_interval_days": review_interval
            }).execute()

def normalize_misconception(text: str | None) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    filler_phrases = [
        "the student", "the learner", "student", "learner", "seems to", "appears to",
        "shows a misunderstanding of", "shows misunderstanding of",
        "has a misconception about", "has a misunderstanding about", "misunderstands",
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
    now = datetime.utcnow().isoformat()
    existing = None
    if misconception:
        res = supabase.table("misconceptions").select("id, occurrences").eq("session_id", session_id).ilike("concept", concept).ilike("misconception", misconception).eq("resolved", 0).order("id", desc=True).limit(1).execute()
        existing = res.data[0] if res.data else None

    if existing:
        supabase.table("misconceptions").update({
            "occurrences": existing["occurrences"] + 1,
            "severity": severity,
            "evidence": evidence,
            "suggested_intervention": suggested_intervention,
            "last_detected": now,
            "resolved": 0
        }).eq("id", existing["id"]).execute()
    else:
        supabase.table("misconceptions").insert({
            "session_id": session_id,
            "concept": concept,
            "misconception": misconception or "unspecified_misconception",
            "evidence": evidence,
            "severity": severity,
            "suggested_intervention": suggested_intervention,
            "occurrences": 1,
            "resolved": 0,
            "first_detected": now,
            "last_detected": now
        }).execute()

def get_active_misconceptions(
    session_id: str,
    concept: str | None = None,
) -> list[dict]:
    query = supabase.table("misconceptions").select("*").eq("session_id", session_id).eq("resolved", 0).order("occurrences", desc=True).order("last_detected", desc=True)
    if concept:
        query = query.ilike("concept", concept)
    res = query.execute()
    return res.data

def resolve_misconceptions(
    session_id: str,
    concept: str,
    misconception_text: str | None = None,
):
    query = supabase.table("misconceptions").update({"resolved": 1}).eq("session_id", session_id).ilike("concept", concept).eq("resolved", 0)
    if misconception_text:
        query = query.ilike("misconception", misconception_text)
    query.execute()

def get_learner_state(session_id: str) -> list[dict]:
    res = supabase.table("learner_state").select("*").eq("session_id", session_id).order("mastery").execute()
    return res.data

def record_metacognitive_checkin(
    session_id: str,
    concept: str,
    confidence_rating: int,
    reflection: str | None = None,
):
    now = datetime.utcnow().isoformat()
    supabase.table("metacognitive_checkins").insert({
        "session_id": session_id,
        "concept": concept,
        "confidence_rating": confidence_rating,
        "reflection": reflection,
        "created_at": now
    }).execute()

def get_latest_metacognitive_checkin(
    session_id: str,
    concept: str,
):
    res = supabase.table("metacognitive_checkins").select("confidence_rating").eq("session_id", session_id).ilike("concept", concept).order("id", desc=True).limit(1).execute()
    return res.data[0]["confidence_rating"] if res.data else None

def upsert_flashcard_progress(session_id: str, total: int, mastered: int):
    now = datetime.utcnow().isoformat()
    res = supabase.table("progress").select("*").eq("session_id", session_id).limit(1).execute()
    res.data = res.data[0] if res.data else None
    if res.data:
        supabase.table("progress").update({
            "flashcards_total": total,
            "flashcards_mastered": mastered,
            "updated_at": now
        }).eq("session_id", session_id).execute()
    else:
        supabase.table("progress").insert({
            "session_id": session_id,
            "flashcards_total": total,
            "flashcards_mastered": mastered,
            "updated_at": now
        }).execute()

def get_progress(session_id: str) -> dict[str, float | int]:
    res = supabase.table("progress").select("*").eq("session_id", session_id).limit(1).execute()
    res.data = res.data[0] if res.data else None
    row = res.data
    if not row:
        return {"quiz_avg": 0, "mastery_pct": 0}
    quiz_avg = row.get("quiz_score_total", 0) / max(row.get("quiz_attempts", 0), 1)
    mastery_pct = row.get("flashcards_mastered", 0) / max(row.get("flashcards_total", 0), 1) * 100
    return {"quiz_avg": round(quiz_avg, 1), "mastery_pct": round(mastery_pct)}

def upsert_card_schedule(session_id: str, card_id: str, front: str, next_review: str):
    res = supabase.table("card_schedule").select("id").eq("id", card_id).limit(1).execute()
    res.data = res.data[0] if res.data else None
    if not res.data:
        supabase.table("card_schedule").insert({
            "id": card_id,
            "session_id": session_id,
            "front": front,
            "next_review": next_review
        }).execute()

def get_card_schedule(card_id: str):
    res = supabase.table("card_schedule").select("*").eq("id", card_id).limit(1).execute()
    res.data = res.data[0] if res.data else None
    return res.data

def update_card_schedule(card_id: str, easiness: float, interval: int, repetitions: int, next_review: str):
    supabase.table("card_schedule").update({
        "easiness": easiness,
        "interval": interval,
        "repetitions": repetitions,
        "next_review": next_review
    }).eq("id", card_id).execute()

def get_due_card_ids(session_id: str) -> list[str]:
    # Supabase/Postgres doesn't directly support the SQLite CASE WHEN sorting via REST simply,
    # so we pull all cards for session and sort in Python.
    res = supabase.table("card_schedule").select("id, next_review").eq("session_id", session_id).execute()
    now_str = datetime.utcnow().isoformat()
    rows = res.data
    def sort_key(row):
        due = 0 if row.get("next_review", "") <= now_str else 1
        return (due, row.get("next_review", ""))
    rows.sort(key=sort_key)
    return [row["id"] for row in rows]

def get_learning_analytics(session_id: str) -> dict:
    state_list = get_learner_state(session_id)
    state_list.sort(key=lambda x: x.get("mastery", 0), reverse=True)
    
    total_concepts = len(state_list)
    average_mastery = sum(item.get("mastery", 0) for item in state_list) / total_concepts if total_concepts else 0.0
    mastered_concepts = [item for item in state_list if item.get("mastery", 0) >= 70]
    weak_concepts = [item for item in state_list if item.get("mastery", 0) < 70]
    
    now_iso = datetime.utcnow().isoformat()
    due_reviews = [item for item in state_list if item.get("next_review_at") and item["next_review_at"] <= now_iso]
    
    misconceptions = get_active_misconceptions(session_id)
    average_confidence = sum(item.get("confidence", 0) for item in state_list) / total_concepts if total_concepts else 0.0

    return {
        "overall_mastery": round(average_mastery, 2),
        "total_concepts": total_concepts,
        "mastered_concepts": len(mastered_concepts),
        "weak_concepts": len(weak_concepts),
        "due_reviews": len(due_reviews),
        "active_misconceptions": len(misconceptions),
        "average_confidence": round(average_confidence, 2),
        "concepts": state_list,
        "weak_concept_details": weak_concepts,
        "due_review_details": due_reviews,
        "misconceptions": misconceptions,
    }

def get_cumulative_learning_analytics(user_id: int) -> dict:
    # Requires an RPC or complex joins. Since REST doesn't support JOINs natively without FKs cleanly mapped in PostgREST,
    # and we have them mapped, we can do it via a Supabase query if needed, but it's simpler to fetch all sessions for the user and aggregate in Python.
    res_sessions = supabase.table("sessions").select("session_id").eq("user_id", user_id).execute()
    session_ids = [s["session_id"] for s in res_sessions.data]
    
    if not session_ids:
        return {
            "overall_mastery": 0.0, "average_confidence": 0.5, "total_concepts": 0,
            "mastered_concepts": 0, "weak_concepts": 0, "due_reviews": 0,
            "active_misconceptions": 0, "resolved_misconceptions": 0,
            "concepts": [], "weak_concept_details": [], "due_review_details": [],
            "misconceptions": [], "resolved_misconceptions_list": []
        }
    
    res_ls = supabase.table("learner_state").select("*").in_("session_id", session_ids).execute()
    # Aggregation in python
    concept_map = {}
    for row in res_ls.data:
        c = row["concept"]
        if c not in concept_map:
            concept_map[c] = []
        concept_map[c].append(row)
        
    state_list = []
    for c, rows in concept_map.items():
        state_list.append({
            "concept": c,
            "mastery": sum(r["mastery"] for r in rows) / len(rows),
            "confidence": sum(r["confidence"] for r in rows) / len(rows),
            "attempts": sum(r["attempts"] for r in rows),
            "correct_attempts": sum(r["correct_attempts"] for r in rows),
            "recent_score": sum(r["recent_score"] for r in rows) / len(rows),
            "needs_examples": sum(r["needs_examples"] for r in rows),
            "needs_step_by_step": sum(r["needs_step_by_step"] for r in rows),
            "updated_at": max(r["updated_at"] for r in rows),
            "last_reviewed_at": max((r["last_reviewed_at"] for r in rows if r.get("last_reviewed_at")), default=None),
            "next_review_at": min((r["next_review_at"] for r in rows if r.get("next_review_at")), default=None),
            "review_interval_days": sum(r["review_interval_days"] for r in rows) / len(rows)
        })
    state_list.sort(key=lambda x: x["mastery"], reverse=True)
    
    total_concepts = len(state_list)
    average_mastery = sum(item["mastery"] for item in state_list) / total_concepts if total_concepts else 0.0
    average_confidence = sum(item["confidence"] for item in state_list) / total_concepts if total_concepts else 0.5
    mastered_concepts = [item for item in state_list if item["mastery"] >= 70]
    weak_concepts = [item for item in state_list if item["mastery"] < 70]
    now_iso = datetime.utcnow().isoformat()
    due_reviews = [item for item in state_list if item.get("next_review_at") and item["next_review_at"] <= now_iso]

    res_misc = supabase.table("misconceptions").select("*").in_("session_id", session_ids).execute()
    misc_map = {}
    for row in res_misc.data:
        key = (row["concept"], row["misconception"])
        if key not in misc_map:
            misc_map[key] = []
        misc_map[key].append(row)
        
    misc_list = []
    for (c, m), rows in misc_map.items():
        misc_list.append({
            "concept": c,
            "misconception": m,
            "severity": rows[0]["severity"],
            "occurrences": sum(r["occurrences"] for r in rows),
            "resolved": max(r["resolved"] for r in rows),
            "suggested_intervention": rows[0]["suggested_intervention"]
        })
    misc_list.sort(key=lambda x: x["occurrences"], reverse=True)
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
        "weak_concept_details": [{"concept": c["concept"], "mastery": c["mastery"], "confidence": c["confidence"]} for c in weak_concepts],
        "due_review_details": [{"concept": c["concept"], "mastery": c["mastery"], "confidence": c["confidence"], "next_review_at": c["next_review_at"]} for c in due_reviews],
        "misconceptions": active_misc,
        "resolved_misconceptions_list": resolved_misc,
    }

def save_user(username: str, password_hash: str) -> int:
    now = datetime.utcnow().isoformat()
    res = supabase.table("users").insert({
        "username": username,
        "password_hash": password_hash,
        "created_at": now
    }).execute()
    return res.data[0]["id"]

def get_user_by_username(username: str) -> dict | None:
    res = supabase.table("users").select("*").eq("username", username).limit(1).execute()
    res.data = res.data[0] if res.data else None
    return res.data

def get_user_by_id(user_id: int) -> dict | None:
    res = supabase.table("users").select("*").eq("id", user_id).limit(1).execute()
    res.data = res.data[0] if res.data else None
    return res.data

def create_auth_token(user_id: int, token: str):
    now = datetime.utcnow().isoformat()
    supabase.table("auth_tokens").insert({
        "token": token,
        "user_id": user_id,
        "created_at": now
    }).execute()

def get_user_id_by_token(token: str) -> int | None:
    res = supabase.table("auth_tokens").select("user_id").eq("token", token).limit(1).execute()
    res.data = res.data[0] if res.data else None
    return res.data["user_id"] if res.data else None

def delete_auth_token(token: str):
    supabase.table("auth_tokens").delete().eq("token", token).execute()

def save_learner_profile(
    session_id: str,
    learning_style: str = "adaptive",
    preferred_difficulty: str = "medium",
    strengths: list[str] | None = None,
    weaknesses: list[str] | None = None,
):
    now = datetime.utcnow().isoformat()
    # Preserving exact JSON string compatibility for strengths/weaknesses as per contract
    strengths_str = json.dumps(strengths) if strengths else "[]"
    weaknesses_str = json.dumps(weaknesses) if weaknesses else "[]"
    
    supabase.table("learner_profiles").upsert({
        "session_id": session_id,
        "learning_style": learning_style,
        "preferred_difficulty": preferred_difficulty,
        "strengths": strengths_str,
        "weaknesses": weaknesses_str,
        "updated_at": now
    }).execute()

def get_learner_profile(session_id: str) -> dict | None:
    res = supabase.table("learner_profiles").select("*").eq("session_id", session_id).limit(1).execute()
    res.data = res.data[0] if res.data else None
    row = res.data
    if not row:
        return None
    try:
        row["strengths"] = json.loads(row["strengths"])
    except Exception:
        row["strengths"] = []
    try:
        row["weaknesses"] = json.loads(row["weaknesses"])
    except Exception:
        row["weaknesses"] = []
    return row


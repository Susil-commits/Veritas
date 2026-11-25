"""
Server-Authoritative Math Arcade Round Generator & Grading Service.

Issues time-bounded challenge batches without exposing canonical answers to the
browser, consumes round IDs once upon submission (preventing replay), and
computes authoritative scores, streaks, stars, and fluency metrics server-side.
"""
from __future__ import annotations

import hashlib
import random
import threading
import time
import uuid
from typing import Any

from services.redis_service import redis_service

ROUND_TTL_SECONDS = 900
_LOCAL_ROUNDS: dict[str, dict[str, Any]] = {}
_LOCAL_ROUNDS_LOCK = threading.RLock()


def _build_numeric_options(answer: int | float, *, is_float: bool = False, min_val: int = 1) -> list[int | float]:
    if is_float:
        ans_f = round(float(answer), 2)
        opts: list[int | float] = [ans_f]
        seen = {ans_f}
        attempts = 0
        while len(opts) < 4 and attempts < 40:
            attempts += 1
            delta = round(random.choice([-1.5, -1.0, -0.5, -0.25, 0.25, 0.5, 1.0, 1.5]), 2)
            cand = round(max(0.25, ans_f + delta), 2)
            if cand not in seen:
                seen.add(cand)
                opts.append(cand)
        offset = 0.5
        while len(opts) < 4:
            cand = round(ans_f + offset, 2)
            offset += 0.5
            if cand not in seen:
                seen.add(cand)
                opts.append(cand)
        random.shuffle(opts)
        return opts

    ans_i = int(answer)
    opts_i: list[int | float] = [ans_i]
    seen_i = {ans_i}
    attempts = 0
    while len(opts_i) < 4 and attempts < 40:
        attempts += 1
        delta = random.randint(-4, 4)
        cand = max(min_val, ans_i + (5 if delta == 0 else delta))
        if cand not in seen_i:
            seen_i.add(cand)
            opts_i.append(cand)
    offset = 1
    while len(opts_i) < 4:
        cand = ans_i + offset
        offset += 1
        if cand not in seen_i:
            seen_i.add(cand)
            opts_i.append(cand)
    random.shuffle(opts_i)
    return opts_i


def _gen_question_for_game(game_id: str) -> tuple[str, list[Any], str]:
    """Return (question_prompt, options, canonical_answer_str) for one item."""
    if game_id == "multiplier_matrix":
        a = random.randint(2, 9)
        b = random.randint(2, 9)
        ans = a * b
        return f"{a} × {b}", _build_numeric_options(ans, min_val=2), str(ans)

    if game_id == "division_dungeons":
        b = random.randint(2, 9)
        q = random.randint(2, 10)
        ans = q
        return f"{b * q} ÷ {b}", _build_numeric_options(ans, min_val=1), str(ans)

    if game_id == "two_step_runner":
        kind = random.choice(["mult_add", "mult_sub", "paren_mult", "add_div"])
        if kind == "mult_add":
            a, b, c = random.randint(3, 8), random.randint(2, 7), random.randint(3, 17)
            ans = a * b + c
            prompt = f"({a} × {b}) + {c}"
        elif kind == "mult_sub":
            a, b, c = random.randint(4, 9), random.randint(3, 8), random.randint(2, 11)
            ans = a * b - c
            prompt = f"({a} × {b}) - {c}"
        elif kind == "paren_mult":
            a, b, c = random.randint(2, 7), random.randint(2, 6), random.randint(2, 5)
            ans = (a + b) * c
            prompt = f"({a} + {b}) × {c}"
        else:
            b = random.randint(2, 5)
            q = random.randint(3, 9)
            total = b * q
            a = random.randint(2, total - 2)
            c = total - a
            ans = q
            prompt = f"({a} + {c}) ÷ {b}"
        return prompt, _build_numeric_options(ans, min_val=1), str(ans)

    if game_id == "fraction_fusion":
        if random.random() > 0.4:
            den = random.choice([2, 3, 4, 5])
            num = random.randint(1, den - 1)
            mult = random.choice([2, 3])
            ans = num * mult
            return f"{num}/{den} = ?/{den * mult}", _build_numeric_options(ans, min_val=1), str(ans)
        den = random.choice([3, 4, 5, 6, 8])
        n1 = random.randint(1, den - 1)
        n2 = random.randint(1, den - n1) if den > n1 else 1
        ans = n1 + n2
        return f"{n1}/{den} + {n2}/{den} = ?/{den}", _build_numeric_options(ans, min_val=1), str(ans)

    if game_id == "equation_alchemist":
        kind = random.choice(["add", "sub", "mult", "two_step"])
        if kind == "add":
            x, a = random.randint(2, 13), random.randint(3, 14)
            prompt = f"x + {a} = {x + a}  (Find x)"
        elif kind == "sub":
            x, a = random.randint(6, 17), random.randint(2, 5)
            prompt = f"x - {a} = {x - a}  (Find x)"
        elif kind == "mult":
            x, coef = random.randint(2, 10), random.randint(2, 7)
            prompt = f"{coef}x = {coef * x}  (Find x)"
        else:
            x, coef, a = random.randint(2, 8), random.randint(2, 5), random.randint(2, 9)
            prompt = f"{coef}x + {a} = {coef * x + a}  (Find x)"
        return prompt, _build_numeric_options(x, min_val=1), str(x)

    if game_id == "decimal_dash":
        if random.random() > 0.45:
            whole = random.choice([1, 2, 3, 4, 5])
            den = random.choice([2, 3, 4, 5])
            ans = whole * den
            return f"{whole} ÷ (1/{den})", _build_numeric_options(ans, min_val=1), str(ans)
        a = random.choice([1.5, 2.5, 3.0, 3.5, 4.5])
        b = random.choice([0.5, 1.0, 1.5, 2.0])
        ans_f = round(a + b, 2)
        return f"{a:g} + {b:g}", _build_numeric_options(ans_f, is_float=True), f"{ans_f:g}"

    # Default / geometry_odyssey (6.EE.A.2 expressions & geometry formulas)
    kind = random.choice(["expr_linear", "rect_area", "rect_perim"])
    if kind == "expr_linear":
        n, k, c = random.randint(2, 7), random.randint(2, 5), random.randint(1, 9)
        ans = k * n + c
        return f"Evaluate {k}n + {c} for n = {n}", _build_numeric_options(ans, min_val=1), str(ans)
    if kind == "rect_area":
        w, h = random.randint(3, 12), random.randint(2, 9)
        ans = w * h
        return f"Area (w × h) when w = {w}, h = {h}", _build_numeric_options(ans, min_val=2), str(ans)
    w, h = random.randint(3, 10), random.randint(2, 8)
    ans = 2 * (w + h)
    return f"Perimeter 2(w + h) for w = {w}, h = {h}", _build_numeric_options(ans, min_val=4), str(ans)


def _prune_expired_local_rounds(now: float) -> None:
    expired = [rid for rid, payload in _LOCAL_ROUNDS.items() if now - payload.get("created_at", 0) > ROUND_TTL_SECONDS]
    for rid in expired:
        _LOCAL_ROUNDS.pop(rid, None)


def issue_arcade_round(
    student_id: str,
    game_id: str,
    mode: str = "blitz",
    count: int = 40,
) -> dict[str, Any]:
    """Create and persist a server-issued question batch without leaking answers."""
    round_id = uuid.uuid4().hex
    now = time.time()
    public_questions: list[dict[str, Any]] = []
    answers: dict[str, str] = {}

    bounded_count = max(5, min(int(count), 60))
    for idx in range(bounded_count):
        qid = f"q{idx + 1}_{uuid.uuid4().hex[:8]}"
        prompt, options, answer = _gen_question_for_game(game_id)
        answers[qid] = answer
        answer_digest = hashlib.sha256(f"{round_id}:{qid}:{answer}".encode("utf-8")).hexdigest()
        public_questions.append({
            "qid": qid,
            "question": prompt,
            "options": options,
            "answer_digest": answer_digest,
        })

    record = {
        "round_id": round_id,
        "student_id": student_id,
        "game_id": game_id,
        "mode": mode or "blitz",
        "answers": answers,
        "created_at": now,
    }

    with _LOCAL_ROUNDS_LOCK:
        _prune_expired_local_rounds(now)
        _LOCAL_ROUNDS[round_id] = record

    try:
        redis_service.set_json(f"veritas:arcade:round:{round_id}", record, ex=ROUND_TTL_SECONDS)
    except Exception:
        pass

    return {
        "round_id": round_id,
        "game_id": game_id,
        "mode": record["mode"],
        "expires_in": ROUND_TTL_SECONDS,
        "questions": public_questions,
    }


def consume_and_grade_round(
    round_id: str,
    student_id: str,
    game_id: str,
    submissions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Consume an active round once, verify ownership, and compute authoritative score metrics."""
    now = time.time()
    record: dict[str, Any] | None = None

    with _LOCAL_ROUNDS_LOCK:
        _prune_expired_local_rounds(now)
        record = _LOCAL_ROUNDS.pop(round_id, None)

    if record is None:
        try:
            redis_key = f"veritas:arcade:round:{round_id}"
            fetched = redis_service.get_json(redis_key)
            if isinstance(fetched, dict):
                record = fetched
                redis_service.delete(redis_key)
        except Exception:
            record = None
    else:
        try:
            redis_service.delete(f"veritas:arcade:round:{round_id}")
        except Exception:
            pass

    if not record or (now - float(record.get("created_at", 0))) > ROUND_TTL_SECONDS:
        raise ValueError("Arcade round is invalid, already submitted, or expired.")
    if record.get("student_id") != student_id or record.get("game_id") != game_id:
        raise PermissionError("Arcade round does not belong to this student or game.")

    answers_map: dict[str, str] = record.get("answers") or {}
    seen_qids: set[str] = set()
    score = 0
    streak = 0
    max_streak = 0
    correct_count = 0
    total_answered = 0

    for item in submissions:
        qid = str(item.get("qid") or "").strip()
        if not qid or qid in seen_qids or qid not in answers_map:
            continue
        seen_qids.add(qid)
        total_answered += 1
        expected = answers_map[qid]
        selected = str(item.get("selected") if item.get("selected") is not None else "").strip()

        is_match = selected == expected
        if not is_match:
            try:
                is_match = abs(float(selected) - float(expected)) < 1e-6
            except (ValueError, TypeError):
                is_match = False

        if is_match:
            correct_count += 1
            multiplier = min(5, (streak // 3) + 1)
            score += 100 * multiplier
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
            score = max(0, score - 25)

    stars = 3 if score >= 800 else (2 if score >= 450 else 1)
    return {
        "score": score,
        "stars": stars,
        "streak_max": max_streak,
        "correct_count": correct_count,
        "total_answered": total_answered,
        "mode": record.get("mode", "blitz"),
    }

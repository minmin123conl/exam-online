"""Grading logic."""
from typing import Any, Dict, List, Optional, Tuple

from . import models


def grade_attempt(
    exam: models.Exam,
    answers: Dict[str, Any],
    order_ids: Optional[List[int]] = None,
) -> Tuple[float, float, int, List[Dict[str, Any]]]:
    """Return (score, total_points, num_correct_questions, details).

    If order_ids is provided, details are returned in that order.
    """
    total_points = 0.0
    score = 0.0
    num_correct = 0
    details: List[Dict[str, Any]] = []

    if order_ids:
        by_id = {q.id: q for q in exam.questions}
        questions_iter = [by_id[i] for i in order_ids if i in by_id]
        # Append any questions not in order_ids (defensive)
        seen = set(order_ids)
        questions_iter += [q for q in exam.questions if q.id not in seen]
    else:
        questions_iter = list(exam.questions)

    for q in questions_iter:
        total_points += q.points
        your = answers.get(str(q.id))
        data = q.data or {}
        if q.type == "mc":
            correct = data.get("answer")
            is_correct = (isinstance(your, str) and your.upper() == (correct or "").upper())
            earned = q.points if is_correct else 0.0
            if is_correct:
                num_correct += 1
            score += earned
            details.append({
                "question_id": q.id,
                "type": "mc",
                "section": q.section or "",
                "question": data.get("question", ""),
                "options": data.get("options", {}),
                "correct": correct,
                "your_answer": your,
                "is_correct": is_correct,
                "points": q.points,
                "earned": earned,
            })
        elif q.type == "tf":
            statements = data.get("statements", {})
            correct_map = data.get("answers", {})
            # Score: 4 sub-statements each worth q.points / len(statements)
            n = len(statements) or 4
            per = q.points / n
            earned = 0.0
            your_map = your if isinstance(your, dict) else {}
            sub_correct = {}
            all_correct = True
            for letter in statements.keys():
                your_val = your_map.get(letter)
                correct_val = bool(correct_map.get(letter))
                # Treat missing answer as wrong
                this_correct = (isinstance(your_val, bool) and your_val == correct_val)
                if this_correct:
                    earned += per
                else:
                    all_correct = False
                sub_correct[letter] = this_correct
            if all_correct:
                num_correct += 1
            score += earned
            details.append({
                "question_id": q.id,
                "type": "tf",
                "section": q.section or "",
                "question": data.get("question", ""),
                "statements": statements,
                "correct": correct_map,
                "your_answer": your_map,
                "is_correct": all_correct,
                "points": q.points,
                "earned": earned,
                "sub_correct": sub_correct,
            })
        elif q.type == "sa":
            correct = (data.get("answer") or "").strip()
            your_str = (your or "").strip() if isinstance(your, str) else ""
            # Compare case-insensitively, also strip spaces (so "1 2 3 4" == "1234")
            def _norm(s: str) -> str:
                return "".join(s.lower().split())
            is_correct = bool(correct) and _norm(your_str) == _norm(correct)
            earned = q.points if is_correct else 0.0
            if is_correct:
                num_correct += 1
            score += earned
            details.append({
                "question_id": q.id,
                "type": "sa",
                "section": q.section or "",
                "question": data.get("question", ""),
                "correct": correct,
                "your_answer": your_str,
                "is_correct": is_correct,
                "points": q.points,
                "earned": earned,
            })
        else:
            details.append({
                "question_id": q.id,
                "type": q.type,
                "question": "",
                "correct": None,
                "your_answer": your,
                "is_correct": False,
                "points": q.points,
                "earned": 0.0,
            })
    return score, total_points, num_correct, details

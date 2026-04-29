"""WebSocket route for leaderboard."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session

from .. import models
from ..db import SessionLocal
from ..ws_manager import manager
from .student import _get_leaderboard_entries

router = APIRouter()


@router.websocket("/ws/leaderboard/{exam_id}")
async def leaderboard_ws(websocket: WebSocket, exam_id: int):
    # Check exam exists & allows leaderboard
    db: Session = SessionLocal()
    try:
        exam = db.query(models.Exam).filter(models.Exam.id == exam_id).first()
        if not exam or not exam.show_leaderboard:
            await websocket.close(code=1008)
            return
        await manager.connect(exam_id, websocket)
        # Send initial snapshot
        entries = _get_leaderboard_entries(db, exam_id)
        await websocket.send_json({
            "type": "leaderboard",
            "payload": {
                "exam_id": exam.id,
                "exam_title": exam.title,
                "entries": [e.model_dump(mode="json") for e in entries],
            },
        })
    finally:
        db.close()

    try:
        while True:
            # Keep connection alive; ignore client messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(exam_id, websocket)
    except Exception:
        manager.disconnect(exam_id, websocket)

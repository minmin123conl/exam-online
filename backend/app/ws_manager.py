"""WebSocket connection manager for real-time leaderboard updates."""
from typing import Dict, Set
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # exam_id -> set of websockets
        self.connections: Dict[int, Set[WebSocket]] = {}

    async def connect(self, exam_id: int, ws: WebSocket):
        await ws.accept()
        self.connections.setdefault(exam_id, set()).add(ws)

    def disconnect(self, exam_id: int, ws: WebSocket):
        conns = self.connections.get(exam_id)
        if conns and ws in conns:
            conns.remove(ws)
            if not conns:
                self.connections.pop(exam_id, None)

    async def broadcast(self, exam_id: int, message: dict):
        conns = list(self.connections.get(exam_id, []))
        dead = []
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(exam_id, ws)


manager = ConnectionManager()

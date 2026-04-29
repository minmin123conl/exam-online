"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import admin, student, ws
from .seed import init_db_and_seed

app = FastAPI(title="Exam Online API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(student.router)
app.include_router(ws.router)


@app.on_event("startup")
def on_startup():
    init_db_and_seed()


@app.get("/healthz")
def healthz():
    return {"ok": True}

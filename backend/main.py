"""Health stub only. T3 owns the SPEC §7 endpoints; do not add them here."""

from fastapi import FastAPI

app = FastAPI(title="Bhar - Site-Tuned Model Blend")


@app.get("/health")
def health():
    return {"status": "ok"}

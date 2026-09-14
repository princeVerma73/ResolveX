"""FastAPI application entry point."""

from fastapi import FastAPI

app = FastAPI(title="AI Customer Support & Ticket Automation System")


@app.get("/health")
def health_check():
    return {"status": "ok"}

from fastapi import FastAPI

app = FastAPI(title="AI Gantt Planner")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

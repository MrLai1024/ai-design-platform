"""FastAPI HTTP server for Workflow CRUD + SSE execution."""
from __future__ import annotations

import json
import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.services.workflow.servicer import WorkflowServicer

app = FastAPI(title="AI Workflow API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/v1/workflow/save")
async def save_workflow(request: Request):
    body = await request.json()
    result = await WorkflowServicer.save(body)
    return JSONResponse(result)


@app.get("/api/v1/workflow/list")
async def list_workflows():
    workflows = await WorkflowServicer.list_workflows()
    return JSONResponse({"workflows": workflows})


@app.get("/api/v1/workflow/{workflow_id}")
async def get_workflow(workflow_id: str):
    result = await WorkflowServicer.get(workflow_id)
    if result is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(result)


@app.delete("/api/v1/workflow/{workflow_id}")
async def delete_workflow(workflow_id: str):
    ok = await WorkflowServicer.delete(workflow_id)
    return JSONResponse({"deleted": ok})


@app.post("/api/v1/workflow/{workflow_id}/run")
async def run_workflow(workflow_id: str, request: Request):
    body = await request.json()
    inputs = body if isinstance(body, dict) else {}

    async def event_stream():
        async for event in WorkflowServicer.run(workflow_id, inputs):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/workflow/{workflow_id}/resume")
async def resume_workflow(workflow_id: str, request: Request):
    body = await request.json()

    async def event_stream():
        async for event in WorkflowServicer.resume(workflow_id, body):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/workflow/{workflow_id}/cancel")
async def cancel_workflow(workflow_id: str):
    ok = await WorkflowServicer.cancel(workflow_id)
    return JSONResponse({"cancelled": ok})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")

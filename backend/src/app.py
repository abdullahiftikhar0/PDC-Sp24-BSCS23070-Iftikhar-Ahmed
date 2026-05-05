import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from .routes import challenge, webhooks
from .webhook_processor import WebhookEventWorker

app = FastAPI()

_webhook_worker = WebhookEventWorker()
_webhook_worker_started = False


@app.on_event('startup')
def _start_webhook_worker():
    global _webhook_worker_started
    if os.getenv('WEBHOOK_WORKER_ENABLED', 'true').lower() == 'false':
        return
    _webhook_worker.start()
    _webhook_worker_started = True


@app.on_event('shutdown')
def _stop_webhook_worker():
    if _webhook_worker_started:
        _webhook_worker.stop()


@app.middleware('http')
async def add_student_id_header(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Student-ID'] = os.getenv('STUDENT_ID', 'BSCS23070')
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


app.include_router(challenge.router, prefix="/api")
app.include_router(webhooks.router, prefix="/webhooks")

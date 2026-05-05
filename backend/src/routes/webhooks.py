import hashlib
import json
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from svix.webhooks import Webhook

from ..database.db import create_or_get_webhook_event
from ..database.models import get_db
from ..webhook_processor import process_due_events_once

router = APIRouter()

def _normalize_headers(request: Request) -> dict[str, str]:
    return {k.lower(): v for k, v in request.headers.items()}


@router.post('/clerk')
async def handle_clerk_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
):
    webhook_secret = os.getenv('CLERK_WEBHOOK_SECRET')
    if not webhook_secret:
        raise HTTPException(status_code=500, detail='CLERK_WEBHOOK_SECRET not set')

    body = await request.body()
    payload = body.decode('utf-8')
    headers = _normalize_headers(request)

    verify_sig = os.getenv('CLERK_WEBHOOK_VERIFY_SIGNATURE', 'true').lower() != 'false'
    if verify_sig:
        try:
            wh = Webhook(webhook_secret)
            wh.verify(payload, headers)
        except Exception:
            raise HTTPException(status_code=401, detail='Invalid webhook signature')

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail='Invalid JSON payload')

    event_type = data.get('type') or 'unknown'
    event_id = headers.get('svix-id') or data.get('id')
    if not event_id:
        event_id = f"sha256_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"

    event, created = create_or_get_webhook_event(
        db=db,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
    )
    if not event:
        raise HTTPException(status_code=500, detail='Failed to persist webhook event')

    background_tasks.add_task(process_due_events_once)

    return {
        'status': 'accepted',
        'duplicate': not created,
        'event_id': event_id,
        'event_type': event_type,
    }
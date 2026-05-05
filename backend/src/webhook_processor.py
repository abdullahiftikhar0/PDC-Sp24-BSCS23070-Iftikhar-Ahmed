import json
import logging
import os
import threading
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .database import models
from .database.db import create_challenge_quota, set_user_premium

logger = logging.getLogger(__name__)


PENDING_STATUS = 'pending'
PROCESSING_STATUS = 'processing'
SUCCEEDED_STATUS = 'succeeded'
DEAD_STATUS = 'dead'


SUBSCRIPTION_ACTIVE_TYPES = {
    'subscription.created',
    'subscription.updated',
    'subscription.active',
    'user.subscription.created',
    'user.subscription.updated',
}

SUBSCRIPTION_CANCELED_TYPES = {
    'subscription.canceled',
    'subscription.cancelled',
    'subscription.deleted',
    'user.subscription.canceled',
    'user.subscription.cancelled',
    'user.subscription.deleted',
}


def _extract_user_id(event_type: str, payload: dict) -> str | None:
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None

    if event_type.startswith('user.'):
        return data.get('id')

    for key in ('user_id', 'userId', 'subscriber_id', 'subscriberId', 'clerk_user_id'):
        if data.get(key):
            return data.get(key)

    user_obj = data.get('user')
    if isinstance(user_obj, dict) and user_obj.get('id'):
        return user_obj.get('id')

    return None


def _compute_next_attempt_at(attempts: int) -> datetime:
    base_seconds = int(os.getenv('WEBHOOK_RETRY_BASE_SECONDS', '2'))
    max_seconds = int(os.getenv('WEBHOOK_RETRY_MAX_SECONDS', '60'))

    delay = min(max_seconds, base_seconds * (2 ** max(0, attempts - 1)))
    return datetime.utcnow() + timedelta(seconds=delay)


def _handle_clerk_event(db: Session, event_type: str, payload: dict) -> None:
    user_id = _extract_user_id(event_type, payload)

    if event_type == 'user.created':
        if not user_id:
            raise ValueError('Missing user id for user.created event')
        create_challenge_quota(db, user_id)
        return

    if event_type in SUBSCRIPTION_ACTIVE_TYPES:
        if not user_id:
            raise ValueError(f'Missing user id for {event_type} event')
        set_user_premium(db, user_id, True)
        return

    if event_type in SUBSCRIPTION_CANCELED_TYPES:
        if not user_id:
            raise ValueError(f'Missing user id for {event_type} event')
        set_user_premium(db, user_id, False)
        return

    # Ignore other event types.


def process_event(db: Session, event: models.WebhookEvent) -> bool:
    """Process a single stored webhook event.

    Returns True when processed successfully (or intentionally ignored), False when it should be retried.
    """

    try:
        payload = json.loads(event.payload)
    except Exception as e:
        event.attempts += 1
        event.last_error = f'Invalid JSON payload: {e}'
        event.status = DEAD_STATUS
        db.commit()
        return True

    try:
        _handle_clerk_event(db, event.event_type, payload)
        event.status = SUCCEEDED_STATUS
        event.processed_at = datetime.utcnow()
        event.last_error = None
        db.commit()
        return True
    except Exception as e:
        max_attempts = int(os.getenv('WEBHOOK_MAX_ATTEMPTS', '8'))

        event.attempts += 1
        event.last_error = str(e)

        if event.attempts >= max_attempts:
            event.status = DEAD_STATUS
        else:
            event.status = PENDING_STATUS
            event.next_attempt_at = _compute_next_attempt_at(event.attempts)

        db.commit()
        return False


def process_due_events(db: Session, limit: int = 10) -> int:
    now = datetime.utcnow()

    due_events = (
        db.query(models.WebhookEvent)
        .filter(models.WebhookEvent.status == PENDING_STATUS)
        .filter(models.WebhookEvent.next_attempt_at <= now)
        .order_by(models.WebhookEvent.received_at.asc())
        .limit(limit)
        .all()
    )

    processed_count = 0
    for event in due_events:
        # Best-effort claim to reduce duplicate processing when multiple workers exist.
        event.status = PROCESSING_STATUS
        db.commit()

        # Re-fetch in case the session state got stale after commit.
        event = db.query(models.WebhookEvent).filter(models.WebhookEvent.id == event.id).first()
        if not event:
            continue

        # If another worker grabbed it, skip.
        if event.status != PROCESSING_STATUS:
            continue

        process_event(db, event)
        processed_count += 1

    return processed_count


def process_due_events_once(limit: int = 10) -> int:
    """Convenience helper for BackgroundTasks."""
    db = models.SessionLocal()
    try:
        return process_due_events(db, limit=limit)
    finally:
        db.close()


class WebhookEventWorker:
    def __init__(self) -> None:
        poll_seconds = float(os.getenv('WEBHOOK_WORKER_POLL_SECONDS', '2'))
        self._poll_seconds = max(0.2, poll_seconds)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name='webhook-event-worker', daemon=True)

    def start(self) -> None:
        if self._thread.is_alive():
            return
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                processed = process_due_events_once(limit=10)
                if processed == 0:
                    self._stop_event.wait(self._poll_seconds)
            except Exception:
                logger.exception('Webhook worker loop crashed')
                self._stop_event.wait(self._poll_seconds)

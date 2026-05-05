import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = REPO_ROOT / 'backend'
DEMO_DB_FILE = REPO_ROOT / 'demo_webhook_demo.db'

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault('STUDENT_ID', 'BSCS23070')
os.environ.setdefault('WEBHOOK_RETRY_BASE_SECONDS', '0')
os.environ.setdefault('WEBHOOK_RETRY_MAX_SECONDS', '0')
os.environ.setdefault('WEBHOOK_MAX_ATTEMPTS', '3')
os.environ.setdefault('WEBHOOK_WORKER_ENABLED', 'false')
os.environ.setdefault('CLERK_WEBHOOK_SECRET', 'demo_secret')
os.environ.setdefault('CLERK_WEBHOOK_VERIFY_SIGNATURE', 'false')
os.environ['DATABASE_URL'] = f"sqlite:///{DEMO_DB_FILE.as_posix()}"


from src.database import models  # noqa: E402
from src.database.db import (  # noqa: E402
    create_or_get_webhook_event,
    get_user_entitlement,
    set_user_premium,
)
from src import webhook_processor  # noqa: E402


def _reset_db() -> None:
    models.Base.metadata.drop_all(bind=models.engine)
    models.Base.metadata.create_all(bind=models.engine)


def _print_state(db, user_id: str, event_id: str) -> None:
    entitlement = get_user_entitlement(db, user_id)
    is_premium = entitlement.is_premium if entitlement else None

    event_count = db.query(models.WebhookEvent).count()
    event = (
        db.query(models.WebhookEvent)
        .filter(models.WebhookEvent.event_id == event_id)
        .first()
    )

    print(f"Entitlement: user_id={user_id}, is_premium={is_premium}")
    print(f"Inbox events in DB: {event_count}")
    if not event:
        print("Event: not present")
        return

    print(
        "Event: "
        f"event_id={event.event_id}, "
        f"type={event.event_type}, "
        f"status={event.status}, "
        f"attempts={event.attempts}"
    )


def demo_without_fix() -> None:
    print('\n=== DEMO: WITHOUT FIX (naive one-shot webhook handling) ===')
    _reset_db()

    user_id = 'user_demo'
    event_id = 'evt_demo_1'

    db = models.SessionLocal()
    try:
        set_user_premium(db, user_id, True)
        print('\nInitial state (user is premium):')
        _print_state(db, user_id, event_id)

        input('\nPress Enter to simulate cancellation webhook + handler crash...')
        try:
            raise RuntimeError('simulated handler crash before DB update')
        except Exception as exc:
            print(f"Handler crashed: {exc}")

        print('\nAfter crash (no durable inbox, no retry):')
        _print_state(db, user_id, event_id)
        print('\nResult: user stays premium because the cancellation was lost.')
    finally:
        db.close()


def demo_with_fix() -> None:
    print('\n=== DEMO: WITH FIX (inbox + idempotency + retry) ===')
    _reset_db()

    user_id = 'user_demo'
    event_id = 'evt_demo_1'
    payload = '{"type":"subscription.canceled","data":{"user_id":"user_demo"}}'

    db = models.SessionLocal()
    try:
        set_user_premium(db, user_id, True)
        print('\nInitial state (user is premium):')
        _print_state(db, user_id, event_id)

        input('\nPress Enter to persist the webhook event into the inbox...')
        event, created = create_or_get_webhook_event(
            db=db,
            event_id=event_id,
            event_type='subscription.canceled',
            payload=payload,
        )
        print(f"Event persisted (created={created}).")
        _print_state(db, user_id, event_id)

        input('\nPress Enter to simulate a transient failure on first processing...')
        original_set_user_premium = webhook_processor.set_user_premium
        call_count = {'n': 0}

        def flaky_set_user_premium(db_session, uid, is_premium):
            call_count['n'] += 1
            if call_count['n'] == 1:
                raise RuntimeError('simulated transient failure')
            return original_set_user_premium(db_session, uid, is_premium)

        webhook_processor.set_user_premium = flaky_set_user_premium
        try:
            webhook_processor.process_due_events(db, limit=1)
        finally:
            webhook_processor.set_user_premium = original_set_user_premium

        db.refresh(event)
        print('\nAfter first attempt (failed, but event is still stored for retry):')
        _print_state(db, user_id, event_id)

        input('\nPress Enter to retry processing (should succeed)...')
        webhook_processor.process_due_events(db, limit=1)
        db.refresh(event)

        print('\nAfter retry (succeeded):')
        _print_state(db, user_id, event_id)
        print('\nResult: user is no longer premium; transient failure did not cause permanent inconsistency.')
    finally:
        db.close()


def main() -> None:
    while True:
        print('\nStudySync Demo Menu')
        print('1) Show WITHOUT fix')
        print('2) Show WITH fix')
        print('q) Quit')

        choice = input('Select an option: ').strip().lower()
        if choice == '1':
            demo_without_fix()
        elif choice == '2':
            demo_with_fix()
        elif choice in {'q', 'quit', 'exit'}:
            return
        else:
            print('Invalid option.')


if __name__ == '__main__':
    main()

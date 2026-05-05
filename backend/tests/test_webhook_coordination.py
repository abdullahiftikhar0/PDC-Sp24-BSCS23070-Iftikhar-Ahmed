import os
from pathlib import Path
import unittest


# Configure an isolated sqlite DB for tests BEFORE importing app/modules.
TEST_DB_FILE = Path(__file__).with_name('test_webhook_coordination.db')
if TEST_DB_FILE.exists():
    TEST_DB_FILE.unlink()

os.environ['DATABASE_URL'] = f"sqlite:///{TEST_DB_FILE.as_posix()}"
os.environ['WEBHOOK_RETRY_BASE_SECONDS'] = '0'
os.environ['WEBHOOK_RETRY_MAX_SECONDS'] = '0'
os.environ['WEBHOOK_MAX_ATTEMPTS'] = '3'
os.environ['WEBHOOK_WORKER_ENABLED'] = 'false'

# Also satisfy the required header middleware.
os.environ['STUDENT_ID'] = os.environ.get('STUDENT_ID', 'TEST_STUDENT_ID')


from src.database import models  # noqa: E402
from src.database.db import create_or_get_webhook_event, get_user_entitlement, set_user_premium  # noqa: E402
from src import webhook_processor  # noqa: E402
from src.app import app  # noqa: E402


class TestWebhookCoordination(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        # Release any pooled connections so Windows can delete the sqlite file.
        try:
            models.engine.dispose()
        except Exception:
            pass

        if TEST_DB_FILE.exists():
            try:
                TEST_DB_FILE.unlink()
            except PermissionError:
                # Best-effort cleanup; on Windows the sqlite file may remain locked by a lingering handle.
                pass

    def test_student_id_header_is_present(self):
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            res = client.get('/api/quota', headers={'Authorization': 'Bearer fake'})
            # Even on error responses, middleware must attach the header.
            self.assertIn('X-Student-ID', res.headers)
            self.assertEqual(res.headers['X-Student-ID'], os.environ['STUDENT_ID'])

    def test_webhook_event_is_idempotent_by_event_id(self):
        db = models.SessionLocal()
        try:
            payload = '{"type":"subscription.canceled","data":{"user_id":"user_123"}}'

            event1, created1 = create_or_get_webhook_event(
                db=db,
                event_id='evt_1',
                event_type='subscription.canceled',
                payload=payload,
            )
            event2, created2 = create_or_get_webhook_event(
                db=db,
                event_id='evt_1',
                event_type='subscription.canceled',
                payload=payload,
            )

            self.assertTrue(created1)
            self.assertFalse(created2)
            self.assertEqual(event1.id, event2.id)

            count = (
                db.query(models.WebhookEvent)
                .filter(models.WebhookEvent.event_id == 'evt_1')
                .count()
            )
            self.assertEqual(count, 1)
        finally:
            db.close()

    def test_cancellation_retries_and_eventually_applies(self):
        user_id = 'user_retry'

        db = models.SessionLocal()
        try:
            set_user_premium(db, user_id, True)

            payload = '{"type":"subscription.canceled","data":{"user_id":"user_retry"}}'
            event, created = create_or_get_webhook_event(
                db=db,
                event_id='evt_retry_1',
                event_type='subscription.canceled',
                payload=payload,
            )
            self.assertTrue(created)

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
            self.assertEqual(event.attempts, 1)
            self.assertEqual(event.status, webhook_processor.PENDING_STATUS)

            # Second attempt should succeed.
            webhook_processor.process_due_events(db, limit=1)
            db.refresh(event)

            self.assertEqual(event.status, webhook_processor.SUCCEEDED_STATUS)

            entitlement = get_user_entitlement(db, user_id)
            self.assertIsNotNone(entitlement)
            self.assertFalse(entitlement.is_premium)
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()

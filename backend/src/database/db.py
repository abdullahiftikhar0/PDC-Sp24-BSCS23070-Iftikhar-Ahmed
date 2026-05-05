from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta
from . import models


def get_challenge_quota(db: Session, user_id: str):
    return (db.query(models.ChallengeQuota)
            .filter(models.ChallengeQuota.user_id == user_id)
            .first())


def create_challenge_quota(db: Session, user_id: str):
    existing_quota = get_challenge_quota(db, user_id)
    if existing_quota:
        return existing_quota

    db_quota = models.ChallengeQuota(user_id=user_id)
    db.add(db_quota)
    db.commit()
    db.refresh(db_quota)
    return db_quota


def get_user_entitlement(db: Session, user_id: str):
    return (db.query(models.UserEntitlement)
            .filter(models.UserEntitlement.user_id == user_id)
            .first())


def set_user_premium(db: Session, user_id: str, is_premium: bool):
    entitlement = get_user_entitlement(db, user_id)
    if not entitlement:
        entitlement = models.UserEntitlement(user_id=user_id, is_premium=is_premium)
        db.add(entitlement)
    else:
        entitlement.is_premium = is_premium

    db.commit()
    db.refresh(entitlement)
    return entitlement


def create_or_get_webhook_event(db: Session, event_id: str, event_type: str, payload: str):
    event = models.WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        status='pending',
        attempts=0,
        received_at=datetime.utcnow(),
        next_attempt_at=datetime.utcnow(),
    )
    db.add(event)
    try:
        db.commit()
        db.refresh(event)
        return event, True
    except IntegrityError:
        db.rollback()
        existing = (db.query(models.WebhookEvent)
                    .filter(models.WebhookEvent.event_id == event_id)
                    .first())
        return existing, False


def reset_quota_if_needed(db: Session, quota: models.ChallengeQuota):
    now = datetime.now()
    if now - quota.last_reset_date > timedelta(hours=24):
        quota.quota_remaining = 10
        quota.last_reset_date = now
        db.commit()
        db.refresh(quota)
    return quota


def create_challenge(
    db: Session,
    difficulty: str,
    created_by: str,
    title: str,
    options: str,
    correct_answer_id: int,
    explanation: str
):
    db_challenge = models.Challenge(
        difficulty=difficulty,
        created_by=created_by,
        title=title,
        options=options,
        correct_answer_id=correct_answer_id,
        explanation=explanation
    )
    db.add(db_challenge)
    db.commit()
    db.refresh(db_challenge)
    return db_challenge


def get_user_challenges(db: Session, user_id: str):
    return db.query(models.Challenge).filter(models.Challenge.created_by == user_id).all()

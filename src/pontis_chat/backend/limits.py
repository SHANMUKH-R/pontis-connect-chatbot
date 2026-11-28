"""Postgres-backed limits shared by workers and preserved across restarts."""

import hashlib
from datetime import UTC, timedelta

from fastapi import HTTPException, Request
from sqlalchemy import text

from pontis_chat.backend.database import DatabaseDep
from pontis_chat.dependency_injectors import AppConfigDep


def enforce_limits(request: Request, db: DatabaseDep, config: AppConfigDep) -> None:
    # Only use the ASGI peer. Uvicorn may resolve forwarded IPs from explicitly
    # trusted proxy addresses; never trust arbitrary X-Forwarded-For headers here.
    peer = request.client.host if request.client else "unknown"
    ip_hash = hashlib.sha256(peer.encode()).hexdigest()
    with db.begin():
        # Serialize the short reservation transaction so concurrent workers cannot
        # overspend either budget. The model call runs after this lock is released.
        db.execute(text("SELECT pg_advisory_xact_lock(72419283)"))
        now = db.scalar(text("SELECT clock_timestamp()"))
        today = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = now - timedelta(seconds=60)
        db.execute(
            text("DELETE FROM request_budget WHERE time < :cutoff"),
            {"cutoff": min(today, cutoff)},
        )
        recent = db.execute(
            text(
                "SELECT count(*), min(time) FROM request_budget WHERE ip_hash = :ip AND time > :cutoff"
            ),
            {"ip": ip_hash, "cutoff": cutoff},
        ).one()
        daily = db.scalar(
            text("SELECT count(*) FROM request_budget WHERE time >= :today"),
            {"today": today},
        )
        if recent[0] >= config.requests_per_minute:
            retry = max(
                1, int((recent[1] + timedelta(seconds=60) - now).total_seconds()) + 1
            )
            raise HTTPException(
                429,
                "Too many requests. Try again shortly.",
                headers={"Retry-After": str(retry)},
            )
        if daily >= config.daily_request_cap:
            retry = max(1, int((today + timedelta(days=1) - now).total_seconds()) + 1)
            raise HTTPException(
                429,
                "Daily request budget exhausted.",
                headers={"Retry-After": str(retry)},
            )
        db.execute(
            text("INSERT INTO request_budget (ip_hash, time) VALUES (:ip, :time)"),
            {"ip": ip_hash, "time": now},
        )

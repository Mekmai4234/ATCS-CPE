"""Project-wide durable budgets and an operator-attested, fail-closed Free Tier gate.

Local rolling 60s/24h accounting is conservative admission control, NOT Google's
remaining balance or reset clock. Consumers must wrap EVERY outbound request,
including countTokens and embedding, through call(). No key rotation/fallback.
"""

import argparse
import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

import sqlalchemy as sa
from pydantic import Field, model_validator
from sqlalchemy.dialects.sqlite import insert

from . import database as db
from .config import PROJECT_ROOT, Settings
from .errors import AppError
from .schemas import Schema


class Limits(Schema):
    rpm: int = Field(gt=0, le=1_000_000)
    tpm: int = Field(gt=0, le=1_000_000_000)
    rpd: int = Field(gt=0, le=10_000_000)
    user_rpm: int = Field(default=1, gt=0, le=1_000_000)


class ModelGrant(Schema):
    model: str = Field(min_length=1, max_length=150, pattern=r"^[\w.-]+$")
    bucket: str = Field(min_length=1, max_length=100)
    endpoints: list[Literal["generateContent", "embedContent", "countTokens"]] = Field(min_length=1)
    returned_models: list[str] = Field(min_length=1)
    roles: list[Literal["chat", "vision", "embedding", "agent"]] = Field(min_length=1)
    image_capable: bool = False


class FreePolicy(Schema):
    tier: Literal["free"]
    project_ref: str = Field(pattern=r"^[A-Za-z0-9._-]{1,100}$")
    key_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    verified_by: str = Field(min_length=1, max_length=100)
    evidence_ref: str = Field(min_length=1, max_length=160)
    verified_at: datetime
    expires_at: datetime
    pools: dict[str, Limits] = Field(min_length=1)
    models: list[ModelGrant] = Field(min_length=1)

    @model_validator(mode="after")
    def bounded_attestation(self):
        if (
            self.verified_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or not 0 < (self.expires_at - self.verified_at).total_seconds() <= 7 * 86400
            or len({m.model for m in self.models}) != len(self.models)
            or any(m.bucket not in self.pools for m in self.models)
            or any("vision" in m.roles and not m.image_capable for m in self.models)
        ):
            raise ValueError(
                "Policy requires bounded aware timestamps and explicit unique models/pools"
            )
        return self


@dataclass
class ProviderReply:
    value: object
    input_tokens: int | None
    returned_model: str | None
    reservation_id: str | None = None


class QuotaBroker:
    def __init__(self, repository, *, clock=time.time):
        self.repo, self.settings, self.clock = repository, repository.settings, clock

    def policy(self):
        try:
            path = Path(self.settings.gemini_free_policy_file or "")
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            policy = FreePolicy.model_validate_json(path.read_text(encoding="utf-8"))
            now = self.clock()
            key = self.settings.gemini_api_key.get_secret_value()
            if (
                not key
                or policy.key_sha256 != hashlib.sha256(key.encode()).hexdigest()
                or not policy.verified_at.timestamp() <= now < policy.expires_at.timestamp()
            ):
                raise ValueError("Attestation missing/expired/key changed")
            return policy
        except Exception:
            raise AppError(
                "free_tier_unverified", "Operator Free Tier verification required", 503, pause=True
            ) from None

    def access(self, model, endpoint, role=None):
        policy = self.policy()
        grant = next(
            (m for m in policy.models if m.model == model and endpoint in m.endpoints), None
        )
        if grant is None:
            raise AppError(
                "free_model_unverified",
                "Model/endpoint is not explicitly approved",
                503,
                pause=True,
            )
        if role is not None and (
            role not in grant.roles or (role == "vision" and not grant.image_capable)
        ):
            raise AppError(
                "free_model_unverified",
                "Model is not approved for this operation role",
                503,
                pause=True,
            )
        return policy, grant

    def fingerprint(self, policy):
        data = [
            policy.model_dump(mode="json"),
            self.settings.gemini_max_concurrent,
            self.settings.gemini_user_concurrent,
        ]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def install_policy(self, *, review_model_changes=False):
        """Operator-only, stopped-worker acknowledgement. Never resets usage counters."""
        policy = self.policy()
        table = db.v2["policies"]
        with self.repo.db.write() as c:
            c.execute(
                insert(table)
                .values(project=policy.project_ref, digest=self.fingerprint(policy))
                .on_conflict_do_update(
                    index_elements=[table.c.project], set_={"digest": self.fingerprint(policy)}
                )
            )
            if review_model_changes:
                circuit = db.v2["circuits"]
                c.execute(
                    circuit.delete().where(
                        circuit.c.key.startswith(policy.project_ref + ":", autoescape=True),
                        circuit.c.reason == "returned_model_unverified",
                    )
                )

    def reserve(
        self,
        context,
        *,
        model,
        endpoint,
        input_tokens,
        call_key,
        background=False,
        input_hash=None,
        role=None,
    ):
        if (
            type(input_tokens) is not int
            or input_tokens <= 0
            or not isinstance(call_key, str)
            or not 0 < len(call_key) <= 160
        ):
            raise AppError(
                "budget_invalid", "A bounded input-token estimate and call key are required", 422
            )
        if input_hash is not None and (
            not isinstance(input_hash, str)
            or len(input_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in input_hash)
        ):
            raise AppError("budget_invalid", "Request fingerprint must be SHA256", 422)
        binding = self.repo.check_execution(context.job_id, context.lease_token)
        default_role = (
            "embedding"
            if endpoint == "embedContent" or binding["kind"] == "import"
            else "vision"
            if binding["kind"] == "enrich"
            else "agent"
            if binding["kind"] in {"research", "artifact"}
            else "chat"
        )
        role = role or default_role
        allowed = (
            {"vision", "embedding"}
            if binding["kind"] == "enrich"
            else {"embedding"}
            if binding["kind"] == "import"
            else {default_role, "vision", "embedding"}
            if binding["kind"] in {"chat", "analysis", "research", "artifact"}
            else set()
        )
        if (
            role not in allowed
            or (endpoint == "embedContent" and role != "embedding")
            or (endpoint == "generateContent" and role == "embedding")
        ):
            raise AppError("budget_role_denied", "Operation role exceeds this job's authority", 403)
        policy, grant = self.access(model, endpoint, role)
        limits, now = policy.pools[grant.bucket], self.clock()
        if input_tokens > limits.tpm:
            raise AppError(
                "budget_input_too_large", "Request exceeds the verified token budget", 422
            )
        reservations, waiters = db.v2["reservations"], db.v2["waiters"]
        denied = None
        reservation_id = str(uuid4())
        call_key = hashlib.sha256(call_key.encode()).hexdigest()
        with self.repo.db.write() as c:
            job = self.repo._owned(c, context.job_id, context.lease_token)
            if job["deadline_at"] <= now:
                raise AppError("task_timeout", "Task exceeded its deadline", 504)
            background = job["kind"] == "enrich" or background
            if not job["owner_id"]:
                raise AppError(
                    "authentication_required", "A durable active member is required", 401
                )
            pin = db.v2["policies"]
            c.execute(
                insert(pin)
                .values(project=policy.project_ref, digest=self.fingerprint(policy))
                .on_conflict_do_nothing()
            )
            if c.scalar(
                sa.select(pin.c.digest).where(pin.c.project == policy.project_ref)
            ) != self.fingerprint(policy):
                raise AppError(
                    "quota_policy_mismatch",
                    "Workers must use one installed policy",
                    503,
                    pause=True,
                )
            duplicate = c.scalar(
                sa.select(reservations.c.reservation_id).where(
                    reservations.c.project == policy.project_ref,
                    reservations.c.job_id == context.job_id,
                    reservations.c.lease_token == context.lease_token,
                    reservations.c.call_key == call_key,
                )
            )
            if duplicate:
                raise AppError(
                    "reservation_used", "An outbound call key cannot be dispatched twice", 409
                )
            wait_id = hashlib.sha256(f"{policy.project_ref}:{context.job_id}".encode()).hexdigest()
            # Expired/cancelled jobs do not retain queue priority.
            c.execute(
                waiters.delete().where(
                    sa.or_(
                        waiters.c.expires_at <= now,
                        ~sa.exists(
                            sa.select(db.jobs.c.job_id).where(
                                db.jobs.c.job_id == waiters.c.job_id,
                                db.jobs.c.state.in_(["queued", "running"]),
                                db.jobs.c.deadline_at > now,
                            )
                        ),
                    )
                )
            )
            c.execute(
                insert(waiters)
                .values(
                    wait_id=wait_id,
                    project=policy.project_ref,
                    owner_id=job["owner_id"],
                    job_id=context.job_id,
                    priority=1 if background else 0,
                    created_at=now,
                    expires_at=job["deadline_at"],
                )
                .on_conflict_do_nothing()
            )
            live = [
                dict(r)
                for r in c.execute(
                    sa.select(reservations).where(
                        reservations.c.project == policy.project_ref,
                        reservations.c.created_at > now - 86400,
                        reservations.c.state != "cancelled",
                    )
                ).mappings()
                if r["state"] != "held" or r["expires_at"] > now
            ]
            active = [r for r in live if r["state"] in {"held", "sent"} and r["expires_at"] > now]
            pool = [r for r in live if r["bucket"] == grant.bucket]
            minute = [r for r in pool if r["created_at"] > now - 60]
            circuit = db.v2["circuits"]
            circuit_row = (
                c.execute(
                    sa.select(circuit).where(
                        circuit.c.key == f"{policy.project_ref}:{grant.bucket}"
                    )
                )
                .mappings()
                .first()
            )
            blocked = circuit_row["blocked_until"] if circuit_row else 0
            first = (
                c.execute(
                    sa.select(waiters)
                    .where(waiters.c.project == policy.project_ref)
                    .order_by(waiters.c.priority, waiters.c.created_at, waiters.c.wait_id)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            # Per-member caps plus FIFO within priority classes prevent repeated reacquisition
            # by one hot worker while another member is waiting. Interactive beats background.
            if (
                blocked > now
                or len(active) >= self.settings.gemini_max_concurrent
                or sum(r["owner_id"] == job["owner_id"] for r in active)
                >= self.settings.gemini_user_concurrent
                or len(minute) >= limits.rpm
                or len(pool) >= limits.rpd
                or sum(r["tokens"] for r in minute) + input_tokens > limits.tpm
                or sum(r["owner_id"] == job["owner_id"] for r in minute) >= limits.user_rpm
                or (first and first["wait_id"] != wait_id)
            ):
                denied = AppError(
                    "quota_wait",
                    "Local project budget is unavailable",
                    429,
                    True,
                    retry_after_seconds=max(1, min(60, blocked - now)) if blocked > now else 60,
                    retry_time_source="estimate",
                    pause=background,
                )
                if blocked > now:
                    reason = circuit_row["reason"]
                    denied = AppError(
                        reason,
                        "Provider circuit is cooling down",
                        429
                        if reason == "provider_rate_limited"
                        else 504
                        if reason == "provider_timeout"
                        else 503,
                        reason != "returned_model_unverified",
                        retry_after_seconds=min(86400, blocked - now),
                        retry_time_source=circuit_row["time_source"],
                        pause=background,
                    )
            else:
                c.execute(waiters.delete().where(waiters.c.wait_id == wait_id))
                c.execute(
                    reservations.insert().values(
                        reservation_id=reservation_id,
                        project=policy.project_ref,
                        policy_digest=self.fingerprint(policy),
                        bucket=grant.bucket,
                        model=model,
                        endpoint=endpoint,
                        role=role,
                        owner_id=job["owner_id"],
                        job_id=context.job_id,
                        lease_token=context.lease_token,
                        call_key=call_key,
                        input_hash=input_hash,
                        state="held",
                        tokens=input_tokens,
                        created_at=now,
                        expires_at=min(job["deadline_at"], now + self.settings.llm_timeout_seconds),
                        returned_allowlist=grant.returned_models,
                    )
                )
        if denied:
            raise denied  # Preserve the committed durable waiter, rather than roll it back.
        return reservation_id

    def dispatch(self, context, reservation_id):
        self.policy()  # Revoked/expired attestation cannot be used after reservation.
        table = db.v2["reservations"]
        with self.repo.db.write() as c:
            self.repo._owned(c, context.job_id, context.lease_token)
            reserved = (
                c.execute(sa.select(table).where(table.c.reservation_id == reservation_id))
                .mappings()
                .first()
            )
            if not reserved:
                raise AppError("reservation_used", "Reservation is missing", 409)
            policy, grant = self.access(reserved["model"], reserved["endpoint"], reserved["role"])
            pin = db.v2["policies"]
            fingerprint = c.scalar(
                sa.select(pin.c.digest).where(pin.c.project == policy.project_ref)
            )
            if (
                fingerprint != self.fingerprint(policy)
                or grant.bucket != reserved["bucket"]
                or reserved["project"] != policy.project_ref
                or reserved["policy_digest"] != self.fingerprint(policy)
            ):
                raise AppError("quota_policy_mismatch", "Policy changed before dispatch", 503)
            changed = c.execute(
                table.update()
                .where(
                    table.c.reservation_id == reservation_id,
                    table.c.job_id == context.job_id,
                    table.c.lease_token == context.lease_token,
                    table.c.state == "held",
                    table.c.expires_at > self.clock(),
                )
                .values(
                    state="sent", created_at=self.clock(), returned_allowlist=grant.returned_models
                )
            ).rowcount
            if changed != 1:
                raise AppError(
                    "reservation_used", "Reservation is expired or already dispatched", 409
                )

    def settle(self, reservation_id, *, reply=None, error=None, unsent=False):
        table, circuit = db.v2["reservations"], db.v2["circuits"]
        rejected_model = False
        with self.repo.db.write() as c:
            row = (
                c.execute(sa.select(table).where(table.c.reservation_id == reservation_id))
                .mappings()
                .one()
            )
            if row["state"] not in {"held", "sent"}:
                return
            if unsent and row["state"] != "held":
                raise AppError("reservation_sent", "Dispatched requests cannot be refunded", 409)
            values = dict(state="cancelled" if unsent else "completed" if reply else "uncertain")
            if reply:
                if type(reply.input_tokens) is int and 0 <= reply.input_tokens <= 1_000_000_000:
                    values["tokens"] = reply.input_tokens
                reported = reply.returned_model if isinstance(reply.returned_model, str) else None
                rejected_model = (not reported and row["endpoint"] == "generateContent") or (
                    reported is not None and reported not in row["returned_allowlist"]
                )
                values["returned_model"] = reported[:150] if reported else None
            c.execute(
                table.update().where(table.c.reservation_id == reservation_id).values(**values)
            )
            key = f"{row['project']}:{row['bucket']}"
            if rejected_model or (error and error.status_code in {429, 503, 504}):
                failures = (
                    c.scalar(sa.select(circuit.c.failures).where(circuit.c.key == key)) or 0
                ) + 1
                floor = 60 if error and error.status_code == 429 else 15
                application_delay = min(300, floor * 2 ** min(failures - 1, 5))
                hint = getattr(error, "retry_after_seconds", None) or 0
                seconds = max(hint, application_delay)
                if rejected_model:
                    seconds = 7 * 86400  # Requires operator review, never a paid model fallback.
                prior = c.execute(sa.select(circuit).where(circuit.c.key == key)).mappings().first()
                until = max(self.clock() + seconds, prior["blocked_until"] if prior else 0)
                reason = "returned_model_unverified" if rejected_model else error.code
                source = (
                    "provider"
                    if error and error.retry_time_source == "provider" and hint >= application_delay
                    else "estimate"
                )
                if prior and prior["blocked_until"] > self.clock() + seconds:
                    reason, source = prior["reason"], prior["time_source"]
                c.execute(
                    insert(circuit)
                    .values(
                        key=key,
                        failures=failures,
                        blocked_until=until,
                        reason=reason,
                        time_source=source,
                    )
                    .on_conflict_do_update(
                        index_elements=[circuit.c.key],
                        set_={
                            "failures": failures,
                            "blocked_until": until,
                            "reason": reason,
                            "time_source": source,
                        },
                    )
                )
            elif reply:
                c.execute(
                    circuit.delete().where(
                        circuit.c.key == key, circuit.c.blocked_until <= self.clock()
                    )
                )
        if rejected_model:
            raise AppError(
                "returned_model_unverified", "Returned model requires operator review", 503
            )

    async def call(self, context, callback, **request):
        context.check()
        permit = self.reserve(context, **request)
        dispatched = False
        try:
            self.dispatch(context, permit)
            dispatched = True
            async with asyncio.timeout(
                min(context.remaining_seconds, self.settings.llm_timeout_seconds)
            ):
                reply = await callback()
            if not isinstance(reply, ProviderReply):
                raise AppError(
                    "provider_invalid_response", "ProviderReply metadata is required", 502
                )
            self.settle(permit, reply=reply)
            context.check()
            reply.reservation_id = permit
            return reply
        except BaseException as error:
            if isinstance(error, TimeoutError):
                from .provider_errors import provider_error

                normalized = provider_error(504)
                self.settle(permit, error=normalized, unsent=not dispatched)
                raise normalized from None
            self.settle(
                permit, error=error if isinstance(error, AppError) else None, unsent=not dispatched
            )
            raise


def main():
    parser = argparse.ArgumentParser(description="Install an operator-attested Free Tier policy")
    parser.add_argument("--workers-stopped", required=True, action="store_true")
    parser.add_argument("--review-model-changes", action="store_true")
    args = parser.parse_args()
    from .repository import Repository

    settings = Settings()
    database = db.Database(settings.database_url)
    try:
        database.check_schema()
        QuotaBroker(Repository(database, settings)).install_policy(
            review_model_changes=args.review_model_changes
        )
        print(
            "Policy installed; existing quota usage retained. Billing was not inspected or changed."
        )
    except Exception:
        parser.exit(
            2,
            "Policy rejected; verify stopped workers, schema, attestation "
            "and selected configuration.\n",
        )
    finally:
        database.close()


if __name__ == "__main__":
    main()

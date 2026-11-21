"""Ask-your-data chat.

The model never chooses what to look at. The server builds a fixed, bounded evidence pack
for the scope the user picked (one batch, or everything they may see), the adapter turns
it into an answer, and the answer is accepted only if it cites evidence that was supplied
and passes the same safety checks as assessment explanations. Otherwise the user gets a
summary the server wrote from the same evidence. Nothing here writes to the database.
"""

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.gemini import AIDisabled, GeminiAdapter
from app.ai.schema import validate_chat_answer
from app.core.config import Settings
from app.core.time import as_utc, utcnow
from app.db.models import (
    Alert,
    Batch,
    Device,
    DeviceAssignment,
    Observation,
    RiskAssessment,
    SensorReading,
    User,
)
from app.repositories.assessments import latest_assessment
from app.repositories.common import accessible_batches, require_batch
from app.repositories.monitoring import device_visibility
from app.retrieval.query import retrieve
from app.schemas.chat import ChatRequest, ChatResponse, ChatSource
from app.schemas.common import Pagination
from app.services.priorities import rank
from app.services.resources import describe_device

logger = logging.getLogger("harvest.chat")

ITEM_CHARS = 1800
# The same wording as the screens, so the chat never calls a batch "spoiling" or "fresh".
STATUS_LABELS = {
    "unknown": "not assessed",
    "fresh": "low risk",
    "early_decay": "elevated risk",
    "spoiling": "high risk",
    "insufficient_data": "insufficient evidence",
}


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status.replace("_", " "))


FACTOR_WORDS = {
    "deterministic_risk": "the risk score",
    "stale_data_inspection": "no recent readings",
    "insufficient_evidence_inspection": "not enough evidence yet",
    "state_hysteresis_retention": "holding a raised status steady so it does not flip back",
}
SNAKE_CASE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


INLINE_BULLET = re.compile(r"(?<=\S)[ \t]*-[ \t]+(?=[A-Z0-9])")


def plain(text: str) -> str:
    """Internal field names (snake_case) mean nothing to staff: show them as words.

    Also puts bullets the model ran together on one line ("done.- 5 batches- 2 ...")
    back on their own lines.
    """
    text = SNAKE_CASE.sub(lambda m: m.group(0).replace("_", " "), text)
    return INLINE_BULLET.sub("\n- ", text)


POLICY_QUESTION = re.compile(
    r"\b(?:safe|unsafe|edible|eat|eaten|eating|consume|consumption)\b"
    r"|shelf[- ]?life|\bexpir(?:e|es|ed|y|ation)\b|\bdays?\s+(?:left|remaining)\b"
    r"|\bhow\s+long\s+(?:will|can|until|before)\b"
    r"|\b(?:sell|selling|dispose|discard)\b|\bthrow\s+(?:it\s+|them\s+)?(?:away|out)\b",
    re.IGNORECASE,
)
POLICY_ANSWER = (
    "I can't certify that produce is safe, estimate how long it will last, or decide whether to "
    "sell or dispose of it. Those decisions need a person to inspect the produce. This is what "
    "the sensors and records show right now."
)
BATCH_FOLLOW_UPS = [
    "What do the last 24 hours of readings show?",
    "Are any alerts open for this batch?",
    "Which devices have reported for this batch?",
]
PORTFOLIO_FOLLOW_UPS = [
    "Which batch needs inspection first?",
    "Are any devices offline?",
    "Which alerts are open?",
]


@dataclass
class Item:
    id: str
    kind: str
    label: str
    text: str
    batch_id: str | None = None


@dataclass
class Pack:
    scope: dict[str, str]
    items: list[Item] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)


def _num(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _when(value: datetime | None) -> str:
    return "never" if value is None else as_utc(value).strftime("%Y-%m-%d %H:%M UTC")


def _words(value: str) -> str:
    return value.replace("_", " ")


def _span(values: list[float], digits: int = 1) -> str:
    if not values:
        return "no data"
    low, high = _num(min(values), digits), _num(max(values), digits)
    return f"{low} to {high} (avg {_num(sum(values) / len(values), digits)})"


def _week_item(db: Session, batch: Batch, now: datetime) -> Item | None:
    """What happened over the last seven days: fixed queries, written for the model to read."""
    since = now - timedelta(days=7)
    assessments = list(
        db.scalars(
            select(RiskAssessment)
            .where(RiskAssessment.batch_id == batch.id, RiskAssessment.created_at >= since)
            .order_by(RiskAssessment.created_at)
        )
    )
    lines: list[str] = []
    previous = None
    for assessment in assessments:
        if assessment.status != previous:
            score = "" if assessment.score is None else f", score {_num(assessment.score)}"
            lines.append(
                f"{_when(assessment.created_at)}: {status_label(assessment.status)}{score}"
                + (" (first assessment in the period)" if previous is None else "")
            )
            previous = assessment.status
    if not lines:
        return None
    peak = max((a.score for a in assessments if a.score is not None), default=None)
    alerts = list(
        db.scalars(
            select(Alert)
            .where(Alert.batch_id == batch.id, Alert.created_at >= since)
            .order_by(Alert.created_at)
        )
    )
    for alert in alerts:
        cleared = f", cleared {_when(alert.resolved_at)}" if alert.resolved_at else ", still open"
        who = "acknowledged" if alert.acknowledged_at else "not acknowledged"
        lines.append(
            f"{alert.severity.title()} alert ({status_label(alert.trigger_key)}) raised "
            f"{_when(alert.created_at)}{cleared}; {who}"
        )
    row = db.execute(
        select(
            func.min(SensorReading.temperature_c),
            func.max(SensorReading.temperature_c),
            func.min(SensorReading.humidity_pct),
            func.max(SensorReading.humidity_pct),
            func.min(SensorReading.gas_adc),
            func.max(SensorReading.gas_adc),
            func.count(),
        ).where(SensorReading.batch_id == batch.id, SensorReading.source_timestamp >= since)
    ).one()
    if row[6]:
        lines.append(
            f"Readings in the period ({row[6]}): temperature {_num(row[0])} to {_num(row[1])} C, "
            f"humidity {_num(row[2])} to {_num(row[3])} %, gas {row[4]} to {row[5]} ADC "
            "(uncalibrated)"
        )
    if peak is not None:
        lines.append(f"Highest risk score in the period: {_num(peak)}")
    return Item(
        f"history:{batch.id}",
        "history",
        "Last 7 days",
        "Status changes and alerts over the last 7 days: " + "; ".join(lines),
        batch.id,
    )


def _reading_items(db: Session, batch: Batch, now: datetime) -> tuple[list[Item], list[str]]:
    total = (
        db.scalar(
            select(func.count())
            .select_from(SensorReading)
            .where(SensorReading.batch_id == batch.id)
        )
        or 0
    )
    if not total:
        text = "No readings have been recorded for this batch."
        return [Item(f"readings:{batch.id}", "readings", "Sensor readings", text, batch.id)], [
            "No sensor readings have arrived for this batch yet."
        ]
    since = now - timedelta(hours=24)
    rows = db.execute(
        select(
            SensorReading.source_timestamp,
            SensorReading.temperature_c,
            SensorReading.humidity_pct,
            SensorReading.gas_adc,
            SensorReading.gas_voltage_v,
            SensorReading.warming_up,
            SensorReading.simulated,
        )
        .where(SensorReading.batch_id == batch.id, SensorReading.source_timestamp >= since)
        .order_by(SensorReading.source_timestamp)
        .limit(3000)
    ).all()
    latest = db.execute(
        select(
            SensorReading.source_timestamp,
            SensorReading.temperature_c,
            SensorReading.humidity_pct,
            SensorReading.gas_adc,
            SensorReading.gas_voltage_v,
            SensorReading.warming_up,
            SensorReading.simulated,
        )
        .where(SensorReading.batch_id == batch.id)
        .order_by(SensorReading.source_timestamp.desc(), SensorReading.id.desc())
        .limit(1)
    ).one()
    parts = [
        f"{total} readings recorded in total. Latest at {_when(latest.source_timestamp)}: "
        f"temperature {_num(latest.temperature_c)} C, humidity {_num(latest.humidity_pct)} %, "
        f"gas {latest.gas_adc} ADC counts ({_num(latest.gas_voltage_v, 3)} V)"
        f"{', sensor still warming up' if latest.warming_up else ''}"
        f"{', SIMULATED data' if latest.simulated else ', real device'}."
    ]
    for hours in (1, 6, 24):
        cutoff = now - timedelta(hours=hours)
        window = [r for r in rows if as_utc(r.source_timestamp) >= cutoff]
        steady = [r for r in window if not r.warming_up]
        temperature = _span([r.temperature_c for r in steady])
        humidity = _span([r.humidity_pct for r in steady])
        gas = _span([float(r.gas_adc) for r in steady], 0)
        parts.append(
            f"Last {hours}h: {len(window)} readings ({len(window) - len(steady)} warm-up, excluded "
            f"from ranges). temperature C {temperature}; humidity % {humidity}; gas ADC {gas}."
        )
    simulated = sum(1 for r in rows if r.simulated)
    if simulated:
        parts.append(f"{simulated} of the last-24h readings are SIMULATED.")
    parts.append("Gas ADC is a raw, uncalibrated MQ-135 value; a rise can reflect ripening.")
    items = [Item(f"readings:{batch.id}", "readings", "Sensor readings", " ".join(parts), batch.id)]

    buckets: dict[datetime, list[tuple[float, float, int]]] = defaultdict(list)
    for r in rows:
        if r.warming_up:
            continue
        hour = as_utc(r.source_timestamp).replace(minute=0, second=0, microsecond=0)
        buckets[hour].append((r.temperature_c, r.humidity_pct, r.gas_adc))
    if buckets:
        lines = []
        for hour in sorted(buckets):
            values = buckets[hour]
            n = len(values)
            temp = _num(sum(v[0] for v in values) / n)
            humid = _num(sum(v[1] for v in values) / n, 0)
            gas_avg = _num(sum(v[2] for v in values) / n, 0)
            lines.append(f"{hour:%d %H:00} n={n} T={temp}C RH={humid}% gas={gas_avg}")
        items.append(
            Item(
                f"trend:{batch.id}",
                "trend",
                "Hourly trend, last 24h",
                "Hourly averages in UTC, oldest first, warm-up excluded: " + "; ".join(lines),
                batch.id,
            )
        )
    summary = [
        f"Latest reading {_when(latest.source_timestamp)}: {_num(latest.temperature_c)} C, "
        f"{_num(latest.humidity_pct)} % humidity, gas {latest.gas_adc} ADC (uncalibrated)"
        f"{'; this is simulated data' if latest.simulated else ''}."
    ]
    return items, summary


def _batch_pack(db: Session, batch: Batch, actor: User, settings: Settings, now: datetime) -> Pack:
    pack = Pack(scope={"type": "batch", "batch": batch.identifier})
    notes = f" Notes: {batch.notes[:300]}" if batch.notes else ""
    demo = " This is a seeded SYNTHETIC demo batch." if batch.attributes.get("seeded_demo") else ""
    pack.items.append(
        Item(
            f"batch:{batch.id}",
            "batch",
            f"Batch {batch.identifier}",
            f"Batch {batch.identifier}: {batch.commodity}, {batch.quantity:g} {batch.unit}, "
            f"stored at {batch.storage_location}. Registered {_when(batch.created_at)}. "
            f"Current status {status_label(batch.status)}{', archived' if batch.archived else ''}."
            f"{demo}{notes}",
            batch.id,
        )
    )
    pack.summary.append(
        f"Batch {batch.identifier} ({batch.commodity}, {batch.quantity:g} {batch.unit}, "
        f"{batch.storage_location}) has status {status_label(batch.status)}"
        f"{' and is archived' if batch.archived else ''}.{demo}"
    )

    assessment = latest_assessment(db, batch.id)
    if assessment:
        flags = ", ".join(assessment.quality_flags) or "none"
        features = json.dumps(assessment.features, sort_keys=True, default=str)[:1200]
        pack.items.append(
            Item(
                f"assessment:{assessment.id}",
                "assessment",
                "Latest assessment",
                f"Assessed {_when(assessment.created_at)}: "
                f"status {status_label(assessment.status)}, "
                f"score {_num(assessment.score)} of 100 (relative, not a measurement of spoilage). "
                f"Explanation: {assessment.explanation} "
                f"Recommendation: {assessment.recommendation} "
                f"Uncertainty: {assessment.uncertainty} Data-quality flags: {flags}. "
                f"Human review required: {assessment.human_review_required}. Features: {features}",
                batch.id,
            )
        )
        pack.summary.append(
            f"Latest assessment ({_when(assessment.created_at)}): "
            f"{status_label(assessment.status)}, "
            f"score {_num(assessment.score)}. {assessment.recommendation}"
        )
    else:
        pack.summary.append("No assessment has been run for this batch yet.")

    reading_items, reading_summary = _reading_items(db, batch, now)
    pack.items.extend(reading_items)
    week = _week_item(db, batch, now)
    if week:
        pack.items.append(week)
    pack.summary.extend(reading_summary)

    served = db.execute(
        select(DeviceAssignment, Device)
        .join(Device, Device.id == DeviceAssignment.device_id)
        .where(DeviceAssignment.batch_id == batch.id)
        .order_by(DeviceAssignment.assigned_at.desc())
        .limit(10)
    ).all()
    for assignment, device in served:
        status = describe_device(device, settings).connection_status
        end = (
            "currently assigned"
            if assignment.released_at is None
            else f"until {_when(assignment.released_at)}"
        )
        pack.items.append(
            Item(
                f"device:{device.id}",
                "device",
                f"Device {device.identifier}",
                f"Device {device.identifier} "
                f"({'simulated' if device.simulated else 'real hardware'}), "
                f"connection {_words(status)}, last seen {_when(device.last_seen_at)}, firmware "
                f"{device.firmware_version or 'not reported'}. Served this batch from "
                f"{_when(assignment.assigned_at)}, {end}.",
                batch.id,
            )
        )
    if served:
        pack.summary.append(
            "Devices: "
            + "; ".join(
                f"{d.identifier} ({_words(describe_device(d, settings).connection_status)})"
                for _, d in served
            )
            + "."
        )
    else:
        pack.summary.append("No device has been assigned to this batch.")

    alerts = list(
        db.scalars(
            select(Alert)
            .where(Alert.batch_id == batch.id, Alert.resolved_at.is_(None))
            .order_by(Alert.created_at.desc())
            .limit(5)
        )
    )
    for alert in alerts:
        state = "acknowledged" if alert.acknowledged_at else "not acknowledged"
        pack.items.append(
            Item(
                f"alert:{alert.id}",
                "alert",
                f"{alert.severity.title()} alert",
                f"Open {alert.severity} alert raised {_when(alert.created_at)} ({state}): "
                f"{alert.message}",
                batch.id,
            )
        )
    pack.summary.append(
        f"{len(alerts)} open alert{'s' if len(alerts) != 1 else ''}."
        if alerts
        else "No open alerts."
    )

    observations = list(
        db.scalars(
            select(Observation)
            .where(Observation.batch_id == batch.id)
            .order_by(Observation.observed_at.desc())
            .limit(5)
        )
    )
    for obs in observations:
        mould = {True: "visible mould", False: "no visible mould", None: "mould not recorded"}[
            obs.visible_mould
        ]
        pack.items.append(
            Item(
                f"observation:{obs.id}",
                "observation",
                f"Observation {obs.observed_at:%d %b}",
                f"{_words(obs.observation_type)} by staff on {_when(obs.observed_at)}: "
                f"{obs.condition}; "
                f"firmness {obs.firmness or 'not recorded'}; {mould}; weight "
                f"{_num(obs.weight_kg) + ' kg' if obs.weight_kg is not None else 'not recorded'}."
                f"{' Notes: ' + obs.notes[:300] if obs.notes else ''}",
                batch.id,
            )
        )
    if observations:
        pack.summary.append(
            f"Most recent staff observation ({_when(observations[0].observed_at)}): "
            f"{observations[0].condition}."
        )
    else:
        pack.summary.append("No staff observations have been recorded.")

    try:
        for chunk in retrieve(db, batch_id=batch.id, actor=actor, at=now, settings=settings):
            if chunk.source_type in {"guidance", "past_assessment"}:
                pack.items.append(
                    Item(
                        f"chunk:{chunk.id}",
                        chunk.source_type,
                        "Guidance note"
                        if chunk.source_type == "guidance"
                        else "Earlier assessment",
                        chunk.text,
                        batch.id,
                    )
                )
    except Exception:  # Retrieval is optional context; the pack stands without it.
        logger.warning("chat_retrieval_unavailable batch_id=%s", batch.id)
    return pack


def _factor_text(factors: dict[str, float]) -> str:
    parts = [
        f"{FACTOR_WORDS.get(key, key.replace('_', ' '))} (+{value:g})"
        for key, value in factors.items()
        if value
    ]
    return "; ".join(parts) or "nothing, so it ranks low"


def _portfolio_pack(db: Session, actor: User, settings: Settings, now: datetime) -> Pack:
    pack = Pack(scope={"type": "portfolio"})
    batches = list(db.scalars(accessible_batches(actor).where(Batch.archived.is_(False))))
    if not batches:
        pack.items.append(
            Item("portfolio:summary", "portfolio", "Overview", "There are no active batches.")
        )
        pack.summary.append("There are no active batches to report on.")
        return pack
    by_status: dict[str, int] = defaultdict(int)
    for b in batches:
        by_status[b.status] += 1
    counts = ", ".join(f"{n} {status_label(s)}" for s, n in sorted(by_status.items()))
    pack.items.append(
        Item(
            "portfolio:summary",
            "portfolio",
            "Overview",
            f"{len(batches)} active batch{'es' if len(batches) != 1 else ''}: {counts}.",
        )
    )
    pack.summary.append(
        f"{len(batches)} active batch{'es' if len(batches) != 1 else ''}: {counts}."
    )

    ranked = rank(db, actor, settings, Pagination(limit=10, offset=0))
    lines = []
    for item in ranked.items:
        text = (
            f"Priority {item.rank}: batch {item.identifier}, status {status_label(item.status)}, "
            f"priority score {item.score}{' (simulated data)' if item.simulated else ''}. "
            f"What adds to it: {_factor_text(item.factors)}."
            f"{' Operator override: ' + str(item.override_rationale) if item.override_rank else ''}"
        )
        pack.items.append(
            Item(
                f"priority:{item.batch_id}",
                "priority",
                f"#{item.rank} {item.identifier}",
                text,
                item.batch_id,
            )
        )
        lines.append(f"{item.rank}. {item.identifier} ({status_label(item.status)})")
    if lines:
        note = "" if ranked.ranking_meaningful else " (only one batch, so there is no real ranking)"
        pack.summary.append("Inspection order: " + "; ".join(lines) + "." + note)

    visible = accessible_batches(actor).with_only_columns(Batch.id)
    alerts = db.execute(
        select(Alert, Batch.identifier)
        .join(Batch, Batch.id == Alert.batch_id)
        .where(Alert.resolved_at.is_(None), Alert.batch_id.in_(visible))
        .order_by(Alert.created_at.desc())
        .limit(10)
    ).all()
    for alert, identifier in alerts:
        pack.items.append(
            Item(
                f"alert:{alert.id}",
                "alert",
                f"{alert.severity.title()} alert, {identifier}",
                f"Open {alert.severity} alert on batch {identifier} raised "
                f"{_when(alert.created_at)} "
                f"({'acknowledged' if alert.acknowledged_at else 'not acknowledged'}): "
                f"{alert.message}",
                alert.batch_id,
            )
        )
    pack.summary.append(
        f"{len(alerts)} open alert{'s' if len(alerts) != 1 else ''}."
        if alerts
        else "No open alerts."
    )

    query = select(Device)
    allowed = device_visibility(actor)
    if allowed is not None:
        query = query.where(Device.id.in_(allowed))
    devices = list(db.scalars(query.limit(500)))
    states: dict[str, int] = defaultdict(int)
    for device in devices:
        states[describe_device(device, settings).connection_status] += 1
    unassigned = sum(1 for d in devices if d.batch_id is None) if actor.role != "vendor" else 0
    device_text = (
        f"{len(devices)} devices: "
        + ", ".join(f"{n} {_words(s)}" for s, n in sorted(states.items()))
        if devices
        else "No devices registered."
    ) + (f". {unassigned} not assigned to a batch." if unassigned else ".")
    pack.items.append(Item("devices:summary", "device", "Device health", device_text))
    pack.summary.append(device_text)
    return pack


def _fit(pack: Pack, limit: int) -> list[Item]:
    kept, used = [], 0
    for item in pack.items:
        item.text = item.text[:ITEM_CHARS]
        size = len(item.text) + len(item.id) + 40
        if used + size > limit:
            continue
        kept.append(item)
        used += size
    return kept


def _response(
    pack: Pack,
    kept: list[Item],
    *,
    mode: str,
    answer: str,
    notice: str | None = None,
    answerable: bool = True,
    cited: list[str] | None = None,
    follow_ups: list[str] | None = None,
) -> ChatResponse:
    by_id = {item.id: item for item in kept}
    ids = cited if cited is not None else [item.id for item in kept[:4]]
    return ChatResponse(
        answer=answer,
        mode=mode,  # type: ignore[arg-type]
        answerable=answerable,
        sources=[
            ChatSource(id=i, label=by_id[i].label, kind=by_id[i].kind, batch_id=by_id[i].batch_id)
            for i in ids
            if i in by_id
        ],
        follow_ups=follow_ups
        if follow_ups is not None
        else (BATCH_FOLLOW_UPS if pack.scope["type"] == "batch" else PORTFOLIO_FOLLOW_UPS),
        notice=notice,
    )


def answer_question(
    db: Session, actor: User, payload: ChatRequest, settings: Settings, adapter: GeminiAdapter
) -> ChatResponse:
    now = utcnow()
    if payload.batch_id:
        pack = _batch_pack(db, require_batch(db, payload.batch_id, actor), actor, settings, now)
    else:
        pack = _portfolio_pack(db, actor, settings, now)
    kept = _fit(pack, settings.chat_evidence_chars)
    summary = " ".join(pack.summary)

    def finish(response: ChatResponse) -> ChatResponse:
        # The question text is never logged: it may contain anything a person typed.
        logger.info(
            "chat user=%s scope=%s mode=%s evidence=%d",
            actor.id,
            payload.batch_id or "portfolio",
            response.mode,
            len(kept),
        )
        return response

    if POLICY_QUESTION.search(payload.message):
        return finish(
            _response(
                pack, kept, mode="policy", answer=f"{POLICY_ANSWER} {summary}", answerable=False
            )
        )
    if not adapter.enabled:
        return finish(
            _response(
                pack,
                kept,
                mode="summary",
                answer=summary,
                notice="AI answers are off for this deployment, so this is a summary of the "
                "current records, not an answer to your question.",
            )
        )
    context = {
        "scope": pack.scope,
        "now_utc": now.isoformat(),
        "question": payload.message,
        "conversation": [turn.model_dump() for turn in payload.history],
        "evidence": [{"id": i.id, "kind": i.kind, "text": i.text} for i in kept],
    }
    try:
        raw = adapter.chat(context)
    except AIDisabled:
        return finish(
            _response(pack, kept, mode="summary", answer=summary, notice="AI answers are off.")
        )
    except Exception:
        logger.warning("chat_provider_failed user=%s", actor.id)
        return finish(
            _response(
                pack,
                kept,
                mode="summary",
                answer=summary,
                notice="The AI service did not answer in time, so this is a summary of the "
                "current records.",
            )
        )
    try:
        result = validate_chat_answer(raw, supplied_ids={i.id for i in kept})
    except (ValueError, TypeError):
        logger.warning("chat_answer_rejected user=%s", actor.id)
        return finish(
            _response(
                pack,
                kept,
                mode="summary",
                answer=summary,
                notice="The AI answer failed the safety checks (it was not grounded in the records "
                "or made a claim this tool must not make), so this is a summary instead.",
            )
        )
    return finish(
        _response(
            pack,
            kept,
            mode="ai",
            answer=plain(result.answer),
            answerable=result.answerable,
            cited=result.evidence_ids,
            follow_ups=[plain(q) for q in result.follow_ups],
        )
    )

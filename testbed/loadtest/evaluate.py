"""Pass/fail of one ladder step, per spec section 6.4."""

from dataclasses import dataclass, field

from loadtest.stats import Row

SLOWDOWN_LIMIT = 1.5
# A step must also be this much slower in absolute terms, so jitter on steps
# of a few tens of ms does not count as overload.
SLOWDOWN_MIN_MS = 250.0
FAILURE_LIMIT = 0.01
WAKE_P95_LIMIT_MS = 2000.0
# Each session must complete at least this share of the steps one session
# completes alone in the same window. A platform that slows its sessions down
# (for example with suspends that block) otherwise looks healthier, because
# fewer steps also mean fewer wakes.
THROUGHPUT_MIN = 0.8


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def _steps_done(rows: dict[str, Row]) -> int:
    return sum(r.requests for name, r in rows.items() if name.startswith("Step_"))


def evaluate_step(step: dict[str, Row], calibration: dict[str, Row], platform: str,
                  users: int | None = None) -> Verdict:
    """users enables the throughput check; calibration runs one session."""
    reasons = []
    if users:
        per_session = _steps_done(step) / users
        alone = _steps_done(calibration)
        if alone and per_session < THROUGHPUT_MIN * alone:
            reasons.append(f"steps per session {per_session:.0f} < {THROUGHPUT_MIN:.0%} of calibration {alone}")
    for name, cal in calibration.items():
        if not name.startswith("Step_") or cal.p95 is None:
            continue
        got = step.get(name)
        if got is None or got.p95 is None:
            reasons.append(f"{name}: missing")
            continue
        if got.p95 > SLOWDOWN_LIMIT * cal.p95 and got.p95 - cal.p95 > SLOWDOWN_MIN_MS:
            reasons.append(f"{name}: p95 {got.p95:.0f} ms > {SLOWDOWN_LIMIT}x calibration {cal.p95:.0f} ms")
    total = step.get("Aggregated")
    if total is None or total.requests == 0:
        reasons.append("Aggregated: missing")
    elif total.failures / total.requests >= FAILURE_LIMIT:
        reasons.append(f"failure ratio {total.failures / total.requests:.2%} >= {FAILURE_LIMIT:.0%}")
    if platform == "substrate":
        wake = step.get("WakeFirstTouch")
        if wake is None or wake.p95 is None:
            reasons.append("WakeFirstTouch: missing")
        elif wake.p95 > WAKE_P95_LIMIT_MS:
            reasons.append(f"WakeFirstTouch p95 {wake.p95:.0f} ms > {WAKE_P95_LIMIT_MS:.0f} ms")
    return Verdict(passed=not reasons, reasons=reasons)

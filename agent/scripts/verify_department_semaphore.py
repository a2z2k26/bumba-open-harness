"""Verify DepartmentSemaphore concurrency enforcement under load.

Standalone diagnostic — no production code changes.

Usage:
    python3 scripts/verify_department_semaphore.py
    python3 scripts/verify_department_semaphore.py --concurrent-runs 20 --semaphore-limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
import time
from pathlib import Path

# Import _semaphore directly to avoid pulling in the full teams package
# (which requires pydantic_ai and other runtime dependencies).
_semaphore_path = Path(__file__).resolve().parent.parent / "teams" / "_semaphore.py"
_spec = importlib.util.spec_from_file_location("_semaphore", _semaphore_path)
assert _spec is not None and _spec.loader is not None
_semaphore_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_semaphore_mod)
DepartmentSemaphore = _semaphore_mod.DepartmentSemaphore  # type: ignore[attr-defined]


async def _worker(
    sem: DepartmentSemaphore,
    dept: str,
    worker_id: int,
    sleep_seconds: float,
    tracker: dict[str, object],
) -> None:
    """Acquire the semaphore, bump tracking counters, sleep, release."""
    async with sem.acquire(dept):
        tracker["current"] += 1  # type: ignore[operator]
        current: int = tracker["current"]  # type: ignore[assignment]
        if current > tracker["peak"]:  # type: ignore[operator]
            tracker["peak"] = current
            tracker["peak_departments"] = frozenset(sem.active_departments())
        tracker["active_count_at_peak"] = sem.active_count
        await asyncio.sleep(sleep_seconds)
        tracker["current"] -= 1  # type: ignore[operator]


async def run_verification(
    concurrent_runs: int,
    semaphore_limit: int,
    sleep_seconds: float = 1.0,
) -> bool:
    """Spawn *concurrent_runs* workers against a single semaphore and verify invariants."""

    sem = DepartmentSemaphore(limit=semaphore_limit)
    tracker: dict[str, object] = {
        "current": 0,
        "peak": 0,
        "peak_departments": frozenset(),
        "active_count_at_peak": 0,
    }
    dept = "test-dept"

    t0 = time.monotonic()

    tasks = [
        asyncio.create_task(_worker(sem, dept, i, sleep_seconds, tracker))
        for i in range(concurrent_runs)
    ]
    await asyncio.gather(*tasks)

    elapsed = time.monotonic() - t0
    peak: int = tracker["peak"]  # type: ignore[assignment]
    peak_depts: frozenset[str] = tracker["peak_departments"]  # type: ignore[assignment]

    # --- assertions -----------------------------------------------------------
    passed = True

    # 1. Peak concurrency must not exceed the limit.
    if peak > semaphore_limit:
        print(
            f"FAIL  peak concurrent ({peak}) exceeded semaphore limit ({semaphore_limit})"
        )
        passed = False
    else:
        print(
            f"PASS  peak concurrent = {peak} (limit = {semaphore_limit})"
        )

    # 2. active_departments() should have included "test-dept" at peak.
    if dept in peak_depts:
        print(f"PASS  active_departments() contained '{dept}' at peak")
    else:
        print(f"FAIL  active_departments() did NOT contain '{dept}' at peak")
        passed = False

    # 3. After all tasks complete, no departments should be active.
    remaining = sem.active_departments()
    if len(remaining) == 0:
        print("PASS  active_departments() is empty after completion")
    else:
        print(f"FAIL  active_departments() still contains: {remaining}")
        passed = False

    # 4. active_count should be 0.
    if sem.active_count == 0:
        print("PASS  active_count = 0 after completion")
    else:
        print(f"FAIL  active_count = {sem.active_count} after completion")
        passed = False

    # --- timing stats ---------------------------------------------------------
    theoretical_min = (concurrent_runs / semaphore_limit) * sleep_seconds
    print()
    print(f"Timing: {elapsed:.2f}s elapsed")
    print(f"        {theoretical_min:.2f}s theoretical minimum ({concurrent_runs} runs / {semaphore_limit} limit * {sleep_seconds}s sleep)")
    print(f"        {concurrent_runs} concurrent runs, semaphore limit {semaphore_limit}")

    print()
    if passed:
        print("RESULT: ALL CHECKS PASSED")
    else:
        print("RESULT: SOME CHECKS FAILED")

    return passed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify DepartmentSemaphore concurrency enforcement."
    )
    parser.add_argument(
        "--concurrent-runs",
        type=int,
        default=10,
        help="Number of concurrent async tasks to spawn (default: 10)",
    )
    parser.add_argument(
        "--semaphore-limit",
        type=int,
        default=3,
        help="Semaphore concurrency limit (default: 3)",
    )
    args = parser.parse_args()

    passed = asyncio.run(
        run_verification(
            concurrent_runs=args.concurrent_runs,
            semaphore_limit=args.semaphore_limit,
        )
    )
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

"""Tests for teams._semaphore module."""

from __future__ import annotations

import asyncio

import pytest

from teams._semaphore import DepartmentSemaphore


@pytest.mark.asyncio
async def test_semaphore_allows_concurrent_up_to_limit():
    sem = DepartmentSemaphore(limit=2)
    entered = []

    async def task(name: str):
        async with sem.acquire("test"):
            entered.append(name)
            await asyncio.sleep(0.05)

    await asyncio.gather(task("a"), task("b"))
    assert sorted(entered) == ["a", "b"]


@pytest.mark.asyncio
async def test_semaphore_serializes_beyond_limit():
    sem = DepartmentSemaphore(limit=1)
    order = []

    async def task(name: str):
        async with sem.acquire("test"):
            order.append(f"{name}-enter")
            await asyncio.sleep(0.02)
            order.append(f"{name}-exit")

    await asyncio.gather(task("a"), task("b"))
    assert order == ["a-enter", "a-exit", "b-enter", "b-exit"] or \
           order == ["b-enter", "b-exit", "a-enter", "a-exit"]


@pytest.mark.asyncio
async def test_semaphore_tracks_active_count():
    sem = DepartmentSemaphore(limit=2)
    assert sem.active_count == 0

    async with sem.acquire("qa"):
        assert sem.active_count == 1
        async with sem.acquire("design"):
            assert sem.active_count == 2
        assert sem.active_count == 1
    assert sem.active_count == 0


@pytest.mark.asyncio
async def test_semaphore_records_department_in_active_set():
    sem = DepartmentSemaphore(limit=2)
    async with sem.acquire("qa"):
        assert "qa" in sem.active_departments()
        async with sem.acquire("strategy"):
            assert "strategy" in sem.active_departments()

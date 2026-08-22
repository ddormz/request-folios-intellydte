import asyncio
import importlib

import pytest


def coordinator_types():
    module = importlib.import_module("src.coordinator")
    return module.FolioCoordinator, module.FolioBusy


def test_ten_companies_never_exceed_global_limit():
    FolioCoordinator, _ = coordinator_types()

    async def scenario():
        coordinator = FolioCoordinator(max_concurrent=4, queue_timeout=1)
        active = 0
        peak = 0

        async def worker(company: int):
            nonlocal active, peak
            async with coordinator.slot("maullin", f"company-{company}"):
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.02)
                active -= 1
                return company

        results = await asyncio.gather(*(worker(company) for company in range(10)))
        return coordinator, peak, results

    coordinator, peak, results = asyncio.run(scenario())

    assert peak == 4
    assert results == list(range(10))
    assert coordinator.lock_count == 0


def test_same_company_is_serialized():
    FolioCoordinator, _ = coordinator_types()

    async def scenario():
        coordinator = FolioCoordinator(max_concurrent=4, queue_timeout=1)
        active = 0
        peak = 0

        async def worker():
            nonlocal active, peak
            async with coordinator.slot("palena", "76123456-0"):
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*(worker() for _ in range(5)))
        return coordinator, peak

    coordinator, peak = asyncio.run(scenario())

    assert peak == 1
    assert coordinator.lock_count == 0


def test_saturation_times_out_and_releases_registry_entry():
    FolioCoordinator, FolioBusy = coordinator_types()

    async def scenario():
        coordinator = FolioCoordinator(max_concurrent=1, queue_timeout=0.02)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def occupying_worker():
            async with coordinator.slot("maullin", "company-a"):
                entered.set()
                await release.wait()

        task = asyncio.create_task(occupying_worker())
        await entered.wait()

        with pytest.raises(FolioBusy):
            async with coordinator.slot("maullin", "company-b"):
                pass

        release.set()
        await task
        return coordinator.lock_count

    assert asyncio.run(scenario()) == 0


def test_cancellation_releases_capacity_and_company_lock():
    FolioCoordinator, _ = coordinator_types()

    async def scenario():
        coordinator = FolioCoordinator(max_concurrent=1, queue_timeout=1)
        entered = asyncio.Event()

        async def canceled_worker():
            async with coordinator.slot("maullin", "company-a"):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(canceled_worker())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        async with coordinator.slot("maullin", "company-a"):
            pass
        return coordinator.lock_count

    assert asyncio.run(scenario()) == 0

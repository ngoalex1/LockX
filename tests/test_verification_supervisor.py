"""Exercise actual OS worker supervision without network or paid AI calls."""
import asyncio
import os
import sys

import verification_supervisor as supervisor


def test_disabled_queue_does_not_start_worker(monkeypatch):
    monkeypatch.delenv("LOCKX_VERIFICATION_QUEUE_ENABLED", raising=False)
    async def run():
        instance = supervisor.VerificationSupervisor()
        await instance.start()
        assert instance.task is None and instance.process is None
        await instance.stop()
    asyncio.run(run())


def test_stop_reaps_real_worker_process(monkeypatch):
    monkeypatch.setenv("LOCKX_VERIFICATION_QUEUE_ENABLED", "1")
    real_spawn = asyncio.create_subprocess_exec
    children = []
    async def spawn(*args, **kwargs):
        process = await real_spawn(sys.executable, "-c", "import time; time.sleep(60)",
                                   start_new_session=os.name == "posix")
        children.append(process)
        return process
    monkeypatch.setattr(supervisor.asyncio, "create_subprocess_exec", spawn)
    async def run():
        instance = supervisor.VerificationSupervisor()
        try:
            await instance.start()
            await instance.start()  # Lifespan cannot launch a second supervisor.
            async with asyncio.timeout(5):
                while not children:
                    await asyncio.sleep(.01)
            assert len(children) == 1 and children[0].returncode is None
        finally:
            await instance.stop()
        assert children[0].returncode is not None
        assert instance.process is None and instance.task is None
    asyncio.run(run())


def test_unexpected_worker_exit_is_restarted(monkeypatch):
    monkeypatch.setenv("LOCKX_VERIFICATION_QUEUE_ENABLED", "1")
    real_spawn = asyncio.create_subprocess_exec
    children = []
    async def spawn(*args, **kwargs):
        code = "raise SystemExit(7)" if not children else "import time; time.sleep(60)"
        process = await real_spawn(sys.executable, "-c", code,
                                   start_new_session=os.name == "posix")
        children.append(process)
        return process
    monkeypatch.setattr(supervisor.asyncio, "create_subprocess_exec", spawn)
    async def run():
        instance = supervisor.VerificationSupervisor()
        try:
            await instance.start()
            async with asyncio.timeout(5):
                while len(children) < 2:
                    await asyncio.sleep(.01)
            assert children[0].returncode == 7
            assert children[1].returncode is None
        finally:
            await instance.stop()
        assert all(process.returncode is not None for process in children)
    asyncio.run(run())

"""Supervise the durable verification worker outside the API process.

The existing volume is single-host. This separates CPU work from the web event
loop without pretending that the service can yet scale horizontally.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

log = logging.getLogger("lockx.verification.supervisor")


class VerificationSupervisor:
    def __init__(self):
        self.task = None
        self.process = None
        self.stopping = False

    async def start(self):
        if os.getenv("LOCKX_VERIFICATION_QUEUE_ENABLED") != "1" or self.task:
            return
        self.task = asyncio.create_task(self.run(), name="verification-supervisor")

    async def run(self):
        delay = 1
        while not self.stopping:
            try:
                self.process = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "verification_worker",
                    cwd=str(Path(__file__).resolve().parent),
                    start_new_session=os.name == "posix",
                )
                log.info("Durable verification worker started")
                code = await self.process.wait()
                # A crashed manager must not leave children competing with its
                # replacement. Leases fence any result from an earlier process.
                await self.terminate_group(grace=2)
                if not self.stopping:
                    log.error("Verification worker exited (%s); restarting", code)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Verification worker could not start")
            if not self.stopping:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def terminate_group(self, *, grace=25):
        process = self.process
        if process is None:
            return
        # Signal the manager first. It stops accepting work and gives active
        # children a bounded drain period; signalling the whole group here
        # would kill those children before they could finish their jobs.
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=grace)
            except asyncio.TimeoutError:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                await process.wait()
        # Children can outlive an exited manager, including after SIGTERM. Each
        # worker has durable leases, so ending this process group loses no job.
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.process = None

    async def stop(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
        await self.terminate_group()
        if self.task:
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from worker.accounts.manager import AccountManager
from worker.accounts.models import Account, AccountStatus
from worker.config.settings import Settings
from worker.queue.executor import JobExecutor, LoginRequiredError
from worker.queue.manager import QueueManager
from worker.queue.models import Job, JobState

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, settings: Settings, accounts: AccountManager, queue: QueueManager) -> None:
        self.settings = settings
        self.accounts = accounts
        self.queue = queue
        self.executor = JobExecutor(settings, accounts)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._running_jobs: set[asyncio.Task] = set()
        self._last_selected_account_id: str | None = None

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="flow-job-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._running_jobs:
            await asyncio.gather(*self._running_jobs, return_exceptions=True)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = await self.queue.pop_ready()
                if job is None:
                    await asyncio.sleep(self.settings.queue.scheduler_interval_seconds)
                    continue
                account = self._select_account(job)
                if account is None:
                    job.stamp("local_waiting_for_account")
                    await self.queue.requeue(job, delay_seconds=3)
                    await asyncio.sleep(self.settings.queue.scheduler_interval_seconds)
                    continue
                job.state = JobState.ASSIGNED
                job.account_id = account.id
                job.stamp("account_selected")
                await self.queue.mark_active(job)
                task = asyncio.create_task(self._run_job(job, account), name=f"job-{job.id}")
                self._running_jobs.add(task)
                task.add_done_callback(self._running_jobs.discard)
            except Exception:
                logger.exception("scheduler loop error")
                await asyncio.sleep(2)

    def _select_account(self, job: Job) -> Account | None:
        now = datetime.now(timezone.utc)
        preferred_account_id = job.payload.get("preferred_account_id")
        if preferred_account_id:
            preferred = self.accounts.get_account(str(preferred_account_id))
            if preferred and self._is_eligible(preferred, now):
                self._last_selected_account_id = preferred.id
                return preferred
        candidates = []
        for account in self.accounts.list_accounts():
            if not self._is_eligible(account, now):
                continue
            score = account.health_score
            score -= account.jobs_running * 30
            score -= account.failure_count * 3
            if account.proxy_enabled:
                score += int((account.proxy_health_score - 100) / 2)
            if account.last_used:
                score += min(20, int((now - account.last_used).total_seconds() / 60))
            if account.proxy_enabled and not account.proxy_url:
                score -= 50
            if account.id == self._last_selected_account_id:
                score -= 35
            candidates.append((score, account))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        selected = candidates[0][1]
        self._last_selected_account_id = selected.id
        return selected

    def _is_eligible(self, account: Account, now: datetime) -> bool:
        if account.status not in {AccountStatus.READY, AccountStatus.BUSY, AccountStatus.COOLDOWN}:
            return False
        if account.settings.cooldown_until and account.settings.cooldown_until > now:
            return False
        return account.jobs_running < account.settings.max_concurrent_jobs

    async def _run_job(self, job: Job, account: Account) -> None:
        try:
            job.stamp("browser_starting")
            account = await self.accounts.ensure_account_running(account.id)
            job.stamp("browser_ready")
        except Exception as exc:
            await self._handle_failure(job, account, JobState.FAILED, exc)
            return
        await self.accounts.mark_job_started(account.id)
        job.state = JobState.PROCESSING
        job.started_at = datetime.now(timezone.utc)
        job.stamp("local_processing_started")
        await self.queue.mark_active(job)
        logger.info(
            "job started job_id=%s worker=%s account=%s generation_type=%s model=%s duration=%s credits=%s retries=%s prompt=%r",
            job.id,
            self.settings.worker_id,
            account.id,
            job.generation_type,
            job.flow_model,
            job.duration,
            job.estimated_credits,
            job.retries,
            job.prompt,
        )
        try:
            job = await asyncio.wait_for(self.executor.run(job, account), timeout=self.settings.queue.job_timeout_seconds)
            await self.accounts.mark_job_finished(account.id, success=True)
            await self.queue.remove_active(job)
            processing_time = None
            if job.started_at and job.completed_at:
                processing_time = (job.completed_at - job.started_at).total_seconds()
            logger.info(
                "job completed job_id=%s worker=%s account=%s model=%s duration=%s credits=%s queue_time=%s processing_time=%s output_urls=%s",
                job.id,
                self.settings.worker_id,
                account.id,
                job.flow_model,
                job.duration,
                job.estimated_credits,
                (job.started_at - job.queued_at).total_seconds() if job.started_at else None,
                processing_time,
                job.output_urls,
            )
        except asyncio.TimeoutError as exc:
            await self._handle_failure(job, account, JobState.TIMEOUT, exc)
        except LoginRequiredError as exc:
            await self._handle_non_retryable_failure(job, account, JobState.FAILED, exc, AccountStatus.TOKEN_EXPIRED)
        except Exception as exc:
            await self._handle_failure(job, account, JobState.FAILED, exc)

    async def _handle_failure(self, job: Job, account: Account, state: JobState, exc: Exception) -> None:
        logger.exception(
            "job failed job_id=%s worker=%s account=%s model=%s duration=%s credits=%s retries=%s error=%s",
            job.id,
            self.settings.worker_id,
            account.id,
            job.flow_model,
            job.duration,
            job.estimated_credits,
            job.retries,
            exc,
        )
        job.last_error = str(exc)
        job.retries += 1
        job.stamp("local_failed")
        await self.accounts.mark_job_finished(account.id, success=False)
        await self.accounts.recover_account(account.id, reason=f"job-{state.value.lower()}")
        if job.retries <= job.max_retries:
            await self.queue.remove_active(job)
            await self.queue.requeue(job, delay_seconds=self.settings.queue.retry_delay_seconds)
        else:
            job.state = state
            job.completed_at = datetime.now(timezone.utc)
            job.stamp("local_terminal")
            await self.queue.remove_active(job)

    async def _handle_non_retryable_failure(
        self,
        job: Job,
        account: Account,
        state: JobState,
        exc: Exception,
        account_status: AccountStatus,
    ) -> None:
        logger.warning(
            "non-retryable job failure job_id=%s worker=%s account=%s state=%s error=%s",
            job.id,
            self.settings.worker_id,
            account.id,
            state,
            exc,
        )
        job.last_error = str(exc)
        job.state = state
        job.completed_at = datetime.now(timezone.utc)
        job.stamp("local_failed")
        job.stamp("local_terminal")
        await self.accounts.mark_job_finished(account.id, success=False)
        await self.accounts.set_account_status(account.id, account_status)
        await self.queue.remove_active(job)

from __future__ import annotations

import asyncio
import base64
import logging
import re
from datetime import datetime, timezone
from typing import Any

from worker.accounts.manager import AccountManager
from worker.accounts.models import Account, AccountStatus
from worker.browser.flowkit_requests import create_project_request, generate_image_request, generate_video_request, get_media_request
from worker.config.settings import Settings
from worker.queue.models import Job, JobState

logger = logging.getLogger(__name__)


class LoginRequiredError(RuntimeError):
    pass


class JobExecutor:
    def __init__(self, settings: Settings, accounts: AccountManager) -> None:
        self.settings = settings
        self.accounts = accounts

    async def run(self, job: Job, account: Account) -> Job:
        job.account_id = account.id
        job.state = JobState.PROCESSING
        job.started_at = datetime.now(timezone.utc)
        job.stamp("executor_started")
        if job.payload.get("flowkit"):
            job.stamp("flowkit_request_started")
            result = await self._run_flowkit_bridge(job, account)
            job.stamp("flowkit_response_received")
            job.output_urls = result.get("output_urls", [])
            job.payload["flowkit_result"] = result
            job.last_error = None
            job.state = JobState.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.stamp("local_completed")
            return job
        if self.accounts.flowkit.status(account.id).get("connected"):
            job.stamp("flowkit_request_started")
            result = await self._run_flowkit_generation(job, account)
            job.stamp("flowkit_response_received")
            job.output_urls = result.get("output_urls", [])
            job.payload["flowkit_result"] = result
            job.last_error = None
            job.state = JobState.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.stamp("local_completed")
            return job

        runtime = self.accounts.runtime_for(account.id)
        if runtime.playwright_context is None:
            job.stamp("browser_recovery_started")
            await self.accounts.recover_account(account.id, reason="missing-playwright-context")
            runtime = self.accounts.runtime_for(account.id)
            job.stamp("browser_recovery_finished")
        if runtime.playwright_context is None:
            raise RuntimeError("Playwright context unavailable after recovery")

        page = await self._flow_page(runtime.playwright_context.pages)
        if page is None:
            await self.accounts.chrome.open_flow(account, runtime)
            page = await self._flow_page(runtime.playwright_context.pages)
        if page is None:
            raise RuntimeError("Google Flow page unavailable")
        if self._is_auth_page(page):
            account.status = AccountStatus.TOKEN_EXPIRED
            account.health_score = max(0, account.health_score - 10)
            account.mark_updated()
            await self.accounts.store.save(account)
            raise LoginRequiredError(f"Google login required for account {account.id}; open VNC and sign in")

        page.set_default_timeout(self.settings.browser.navigation_timeout_ms)
        await page.bring_to_front()
        job.stamp("flow_page_ready")
        await self._apply_flow_settings(page, job)
        job.stamp("flow_settings_applied")
        await self._submit_prompt(page, job.prompt)
        job.stamp("prompt_submitted")
        output_urls = await self._wait_for_outputs(page)
        job.stamp("output_detected")
        job.output_urls = output_urls
        job.last_error = None
        job.state = JobState.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.stamp("local_completed")
        return job

    async def _run_flowkit_bridge(self, job: Job, account: Account) -> dict:
        flowkit_payload = job.payload.get("flowkit")
        if not isinstance(flowkit_payload, dict):
            raise RuntimeError("flowkit payload must be an object")
        method = str(flowkit_payload.get("method") or "api_request")
        params = flowkit_payload.get("params")
        if not isinstance(params, dict):
            raise RuntimeError("flowkit.params must be an object")
        params = {
            **params,
            "generation_type": job.generation_type,
            "flow_model": job.flow_model,
            "duration": job.duration,
            "estimated_credits": job.estimated_credits,
            "flow_settings": job.payload.get("flow_settings"),
        }
        timeout = float(flowkit_payload.get("timeout", self.settings.queue.job_timeout_seconds))
        result = await self.accounts.flowkit.send(account.id, method, params, timeout=timeout)
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        urls = await self._extract_urls(result)
        return {"result": result, "output_urls": urls}

    async def _run_flowkit_generation(self, job: Job, account: Account) -> dict:
        project_title = f"worker-{job.id}"
        generation_prompt = self._generation_prompt(job)
        project_result = await self.accounts.flowkit.send(
            account.id,
            "trpc_request",
            create_project_request(project_title),
            timeout=90,
        )
        if project_result.get("error"):
            raise RuntimeError(f"FlowKit create project failed: {project_result['error']}")
        project_id = self._extract_project_id(project_result)
        if not project_id:
            raise RuntimeError(f"FlowKit create project did not return project id: {project_result}")

        inputs = job.payload.get("inputs") if isinstance(job.payload.get("inputs"), dict) else {}
        image_media_id = str(inputs.get("image_media_id") or "").strip() or None
        image_result: dict[str, Any] | None = None
        output_urls: list[str] = []
        if job.generation_type == "image_to_video" and image_media_id:
            job.stamp("input_image_media_id_used")
        else:
            if job.generation_type in {"image_to_image", "image_to_video"} and not (inputs.get("image_url") or inputs.get("image_data_url") or image_media_id):
                raise RuntimeError("Image input missing: send inputs.image_url, inputs.image_data_url, or inputs.image_media_id.")
            image_result = await self.accounts.flowkit.send(
                account.id,
                "api_request",
                generate_image_request(generation_prompt, project_id, job.flow_model, job.aspect_ratio),
                timeout=90,
            )
            if image_result.get("error") or int(image_result.get("status") or 200) >= 400:
                raise RuntimeError(f"FlowKit image request failed: {image_result}")
            image_media_id = self._extract_media_id(image_result)
            output_urls = await self._extract_urls(image_result)

        if job.generation_type in {"text_to_video", "image_to_video"}:
            if not image_media_id:
                raise RuntimeError(f"FlowKit image request did not return media id for video start frame: {image_result}")
            video_result = await self.accounts.flowkit.send(
                account.id,
                "api_request",
                generate_video_request(generation_prompt, project_id, image_media_id, job.flow_model, job.aspect_ratio),
                timeout=90,
            )
            if video_result.get("error") or int(video_result.get("status") or 200) >= 400:
                raise RuntimeError(f"FlowKit video request failed: {video_result}")
            video_media_id = self._extract_video_media_id(video_result)
            video_urls = await self._extract_video_urls(video_result)
            if not video_urls and video_media_id:
                poll_result = await self._poll_video_media(account, video_media_id)
                video_urls = await self._extract_video_urls(poll_result)
                video_result = {
                    "submit_result": self._redact_encoded_video(video_result),
                    "poll_result": self._redact_encoded_video(poll_result),
                }
            if not video_urls:
                raise RuntimeError(
                    "FlowKit video generation submitted but no playable video URL was returned yet. "
                    f"video_media_id={video_media_id or 'missing'}"
                )
            output_urls = video_urls
            return {
                "project_id": project_id,
                "image_media_id": image_media_id,
                "video_media_id": video_media_id,
                "aspect_ratio": job.aspect_ratio,
                "caption": job.caption,
                "image_result": image_result,
                "video_result": video_result,
                "output_urls": sorted(set(output_urls)),
            }

        return {
            "project_id": project_id,
            "image_media_id": image_media_id,
            "aspect_ratio": job.aspect_ratio,
            "caption": job.caption,
            "image_result": image_result,
            "output_urls": sorted(set(output_urls)),
        }

    def _generation_prompt(self, job: Job) -> str:
        parts = [job.prompt.strip()]
        if job.caption:
            parts.append(f"Image instruction: {job.caption.strip()}")
        if job.generation_type in {"image_to_image", "image_to_video"}:
            inputs = job.payload.get("inputs") if isinstance(job.payload.get("inputs"), dict) else {}
            if inputs.get("image_url") or inputs.get("image_data_url") or inputs.get("image_media_id"):
                parts.append("Use the provided input image as the visual reference.")
        return "\n\n".join(part for part in parts if part)

    async def _extract_urls(self, payload: object) -> list[str]:
        text = str(payload)
        return sorted(set(re.findall(r"https?://[^\s\"'<>}]+", text)))

    async def _extract_video_urls(self, payload: object) -> list[str]:
        if isinstance(payload, dict):
            local_url = self._save_encoded_video(payload)
            if local_url:
                return [local_url]
        urls = await self._extract_urls(payload)
        return [url for url in urls if "/video/" in url or re.search(r"\.(mp4|webm|mov)(\?|$)", url, re.I)]

    def _save_encoded_video(self, payload: dict[str, Any]) -> str | None:
        encoded = self._find_key(payload, "encodedVideo")
        media_id = self._extract_video_media_id(payload) or f"video-{int(datetime.now(timezone.utc).timestamp())}"
        if not isinstance(encoded, str) or not encoded:
            return None
        try:
            binary = base64.b64decode(encoded)
        except Exception:
            return None
        if len(binary) < 12 or binary[4:8] != b"ftyp":
            return None
        video_dir = self.settings.paths.logs_dir / "videos"
        video_dir.mkdir(parents=True, exist_ok=True)
        path = video_dir / f"{media_id}.mp4"
        path.write_bytes(binary)
        return f"/media/videos/{path.name}"

    def _find_key(self, value: object, key: str) -> object | None:
        if isinstance(value, dict):
            if key in value:
                return value[key]
            for child in value.values():
                found = self._find_key(child, key)
                if found is not None:
                    return found
        if isinstance(value, list):
            for child in value:
                found = self._find_key(child, key)
                if found is not None:
                    return found
        return None

    def _redact_encoded_video(self, value: object) -> object:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, child in value.items():
                if key == "encodedVideo" and isinstance(child, str):
                    redacted[key] = f"<redacted encoded mp4: {len(child)} chars>"
                else:
                    redacted[key] = self._redact_encoded_video(child)
            return redacted
        if isinstance(value, list):
            return [self._redact_encoded_video(child) for child in value]
        return value

    def _extract_video_media_id(self, payload: dict) -> str | None:
        data = payload.get("data", payload)
        if isinstance(data, dict):
            operations = data.get("operations") or []
            for operation in operations:
                video = operation.get("operation", {}).get("metadata", {}).get("video", {})
                media_id = video.get("mediaId")
                if self._is_uuid(media_id):
                    return media_id
            workflows = data.get("workflows") or []
            for workflow in workflows:
                media_id = workflow.get("metadata", {}).get("primaryMediaId")
                if self._is_uuid(media_id):
                    return media_id
            media = data.get("media") or []
            for item in media:
                media_id = item.get("name")
                if self._is_uuid(media_id) and item.get("video"):
                    return media_id
        return self._extract_media_id(payload)

    def _is_uuid(self, value: object) -> bool:
        return isinstance(value, str) and bool(
            re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value, re.I)
        )

    async def _poll_video_media(self, account: Account, media_id: str) -> dict:
        interval = 10
        timeout = min(self.settings.queue.job_timeout_seconds, 900)
        elapsed = 0
        last_result: dict[str, Any] = {}
        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
            result = await self.accounts.flowkit.send(
                account.id,
                "api_request",
                get_media_request(media_id),
                timeout=30,
            )
            last_result = result
            if result.get("error") or int(result.get("status") or 200) >= 400:
                continue
            if await self._extract_video_urls(result):
                return result
        return {"error": f"video polling timeout after {timeout}s", "last_result": last_result}

    def _extract_project_id(self, payload: dict) -> str | None:
        text = str(payload)
        patterns = [
            r"projectId['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
            r"id['\"]?\s*[:=]\s*['\"]([0-9a-f-]{20,})['\"]",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def _extract_media_id(self, payload: dict) -> str | None:
        text = str(payload)
        for pattern in [
            r"name['\"]?\s*[:=]\s*['\"]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})['\"]",
            r"mediaId['\"]?\s*[:=]\s*['\"]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})['\"]",
            r"/(?:image|video)/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        ]:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    async def _flow_page(self, pages) -> object | None:
        auth_page = None
        for page in pages:
            if "labs.google" in page.url:
                return page
            if self._is_auth_page(page):
                auth_page = page
        return auth_page

    def _is_auth_page(self, page) -> bool:
        return "accounts.google.com" in page.url or "ServiceLogin" in page.url or "/auth/signin" in page.url

    async def _submit_prompt(self, page, prompt: str) -> None:
        await self._open_prompt_workspace_if_needed(page)
        if self._is_auth_page(page):
            raise LoginRequiredError("Google Flow auth callback failed; click Sign in with Google in VNC")
        selectors = [
            "textarea",
            "[contenteditable='true']",
            "input[type='text']",
            "[role='textbox']",
        ]
        last_error: Exception | None = None
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                await locator.wait_for(state="visible", timeout=10000)
                await locator.fill(prompt)
                break
            except Exception as exc:
                last_error = exc
        else:
            diagnostics = await self._prompt_diagnostics(page)
            raise RuntimeError(f"prompt input not found after opening Flow workspace: {last_error}; page={diagnostics}")

        buttons = [
            "button:has-text('Generate')",
            "button:has-text('Create')",
            "button:has-text('Submit')",
            "button[type='submit']",
        ]
        for selector in buttons:
            try:
                button = page.locator(selector).first
                await button.wait_for(state="visible", timeout=5000)
                await button.click()
                return
            except Exception:
                continue
        await page.keyboard.press("Control+Enter")

    async def _open_prompt_workspace_if_needed(self, page) -> None:
        if await self._has_visible_prompt_input(page):
            return
        for selector in [
            "button:has-text('New project')",
            "button:has-text('Create new project')",
            "button:has-text('Create')",
        ]:
            try:
                button = page.locator(selector).first
                await button.wait_for(state="visible", timeout=3000)
                await button.click()
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                await page.wait_for_timeout(3000)
                if self._is_auth_page(page):
                    raise LoginRequiredError("Google Flow auth callback failed; click Sign in with Google in VNC")
                if await self._has_visible_prompt_input(page):
                    return
            except Exception:
                continue

    async def _has_visible_prompt_input(self, page) -> bool:
        for selector in ["textarea", "[contenteditable='true']", "input[type='text']", "[role='textbox']"]:
            try:
                locator = page.locator(selector).first
                if await locator.is_visible(timeout=1000):
                    box = await locator.bounding_box()
                    if box and box["width"] > 0 and box["height"] > 0:
                        return True
            except Exception:
                continue
        return False

    async def _prompt_diagnostics(self, page) -> dict:
        try:
            return await page.evaluate(
                """() => ({
                    url: location.href,
                    title: document.title,
                    visibleButtons: Array.from(document.querySelectorAll('button')).filter((el) => {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
                    }).slice(0, 20).map((el) => (el.innerText || el.getAttribute('aria-label') || '').trim()),
                    inputs: Array.from(document.querySelectorAll('textarea,input,[contenteditable=true],[role=textbox]')).map((el) => {
                        const r = el.getBoundingClientRect();
                        const s = getComputedStyle(el);
                        return {
                            tag: el.tagName,
                            role: el.getAttribute('role'),
                            type: el.getAttribute('type'),
                            aria: el.getAttribute('aria-label'),
                            placeholder: el.getAttribute('placeholder'),
                            visible: r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none',
                            rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]
                        };
                    })
                })""",
            )
        except Exception as exc:
            return {"diagnostics_error": str(exc)}

    async def _apply_flow_settings(self, page, job: Job) -> None:
        settings = job.payload.get("flow_settings")
        if not isinstance(settings, dict):
            return
        await page.evaluate(
            """(settings) => {
                window.__FLOW_WORKER_SETTINGS__ = settings;
                window.dispatchEvent(new CustomEvent("flow-worker-settings", { detail: settings }));
            }""",
            {
                "generation_type": job.generation_type,
                "model": job.flow_model,
                "duration": job.duration,
                "estimated_credits": job.estimated_credits,
                "presets": settings.get("presets") or {},
            },
        )

    async def _wait_for_outputs(self, page) -> list[str]:
        deadline = asyncio.get_running_loop().time() + self.settings.queue.job_timeout_seconds
        seen: set[str] = set()
        url_pattern = re.compile(r"https?://[^\s\"']+")
        navigation_errors = 0
        while asyncio.get_running_loop().time() < deadline:
            if self._is_auth_page(page):
                raise LoginRequiredError("Google Flow auth callback failed during generation; click Sign in with Google in VNC")
            try:
                links = await page.locator("a").evaluate_all("(els) => els.map(a => a.href).filter(Boolean)")
                for link in links:
                    if "labs.google" not in link:
                        seen.add(link)
                text = await page.locator("body").inner_text(timeout=5000)
                for match in url_pattern.findall(text):
                    if "labs.google" not in match:
                        seen.add(match)
                if seen:
                    return sorted(seen)
                navigation_errors = 0
            except Exception as exc:
                if "Execution context was destroyed" not in str(exc):
                    raise
                navigation_errors += 1
                if navigation_errors > 6:
                    raise RuntimeError("Google Flow kept navigating while waiting for outputs") from exc
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            await asyncio.sleep(5)
        raise asyncio.TimeoutError("timed out waiting for generated output URLs")

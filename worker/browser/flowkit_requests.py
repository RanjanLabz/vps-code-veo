from __future__ import annotations

import random
import time
import uuid
from typing import Any


GOOGLE_FLOW_API = "https://aisandbox-pa.googleapis.com"
GOOGLE_API_KEY = "AIzaSyBtrm0o5ab1c-Ec8ZuLcGt3oJAA5VWt3pY"

IMAGE_MODELS = {
    "nano-banana-2": "NARWHAL",
    "nano-banana-2-edit": "NARWHAL",
    "imagen-4-fast": "GEM_PIX_2",
    "imagen-4-quality": "GEM_PIX_2",
}

VIDEO_MODELS = {
    "veo-3.1-fast": "veo_3_1_i2v_lite_low_priority",
    "veo-3.1-quality": "veo_3_1_i2v_lite_low_priority",
    "veo-3-fast": "veo_3_1_i2v_s_fast",
}


def browser_headers() -> dict[str, str]:
    user_agent = random.choice(
        [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        ]
    )
    platform = '"Windows"' if "Windows" in user_agent else '"Linux"'
    return {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "text/plain;charset=UTF-8",
        "origin": "https://labs.google",
        "referer": "https://labs.google/",
        "sec-ch-ua": '"Not?A_Brand";v="8", "Chromium";v="141", "Google Chrome";v="141"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": platform,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
        "user-agent": user_agent,
        "x-browser-channel": "stable",
        "x-browser-copyright": "Copyright 2025 Google LLC. All rights reserved.",
        "x-browser-validation": "SgDQo8mvrGRdD61Pwo8wyWVgYgs=",
        "x-browser-year": "2025",
        "x-client-data": "CKi1yQEIh7bJAQiktskBCKmdygEIvorLAQiUocsBCIagzQEYv6nKARjRp88BGKqwzwE=",
    }


def client_context(project_id: str, tier: str = "PAYGATE_TIER_TWO") -> dict[str, Any]:
    return {
        "projectId": project_id,
        "recaptchaContext": {
            "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
            "token": "",
        },
        "sessionId": f";{int(time.time() * 1000)}",
        "tool": "PINHOLE",
        "userPaygateTier": tier,
    }


def create_project_request(title: str) -> dict[str, Any]:
    return {
        "url": "https://labs.google/fx/api/trpc/project.createProject",
        "method": "POST",
        "headers": {"content-type": "application/json", "accept": "*/*"},
        "body": {"json": {"projectTitle": title, "toolName": "PINHOLE"}},
    }


def generate_image_request(prompt: str, project_id: str, model: str | None = None) -> dict[str, Any]:
    ts = int(time.time() * 1000)
    ctx = client_context(project_id)
    image_model = IMAGE_MODELS.get(model or "", "NARWHAL")
    body = {
        "clientContext": ctx,
        "requests": [
            {
                "clientContext": {**ctx, "sessionId": f";{ts}"},
                "seed": ts % 1000000,
                "structuredPrompt": {"parts": [{"text": prompt}]},
                "imageAspectRatio": "IMAGE_ASPECT_RATIO_LANDSCAPE",
                "imageModelName": image_model,
            }
        ],
    }
    return {
        "url": f"{GOOGLE_FLOW_API}/v1/projects/{project_id}/flowMedia:batchGenerateImages?key={GOOGLE_API_KEY}",
        "method": "POST",
        "headers": browser_headers(),
        "body": body,
        "captchaAction": "IMAGE_GENERATION",
    }


def generate_video_request(prompt: str, project_id: str, start_media_id: str, model: str | None = None) -> dict[str, Any]:
    model_key = VIDEO_MODELS.get(model or "", "veo_3_1_i2v_lite_low_priority")
    body = {
        "mediaGenerationContext": {"batchId": str(uuid.uuid4())},
        "clientContext": client_context(project_id),
        "requests": [
            {
                "aspectRatio": "VIDEO_ASPECT_RATIO_LANDSCAPE",
                "seed": int(time.time()) % 10000,
                "textInput": {"structuredPrompt": {"parts": [{"text": prompt}]}},
                "videoModelKey": model_key,
                "startImage": {"mediaId": start_media_id},
                "metadata": {"sceneId": str(uuid.uuid4())},
            }
        ],
        "useV2ModelConfig": True,
    }
    return {
        "url": f"{GOOGLE_FLOW_API}/v1/video:batchAsyncGenerateVideoStartImage?key={GOOGLE_API_KEY}",
        "method": "POST",
        "headers": browser_headers(),
        "body": body,
        "captchaAction": "VIDEO_GENERATION",
    }


def get_media_request(media_id: str) -> dict[str, Any]:
    return {
        "url": f"{GOOGLE_FLOW_API}/v1/media/{media_id}?key={GOOGLE_API_KEY}&clientContext.tool=PINHOLE",
        "method": "GET",
        "headers": browser_headers(),
    }

from __future__ import annotations

from typing import Any


MODEL_CATALOG: dict[str, list[dict[str, Any]]] = {
    "text_to_image": [
        {"model": "nano-banana-2", "estimated_credits": 20},
        {"model": "imagen-4-fast", "estimated_credits": 15},
        {"model": "imagen-4-quality", "estimated_credits": 30},
    ],
    "image_to_image": [
        {"model": "nano-banana-2-edit", "estimated_credits": 25},
        {"model": "imagen-4-edit-fast", "estimated_credits": 20},
        {"model": "imagen-4-edit-quality", "estimated_credits": 35},
    ],
    "text_to_video": [
        {"model": "veo-3.1-fast", "duration": 8, "estimated_credits": 160},
        {"model": "veo-3.1-quality", "duration": 8, "estimated_credits": 300},
        {"model": "veo-3-fast", "duration": 8, "estimated_credits": 120},
    ],
    "image_to_video": [
        {"model": "veo-3.1-fast", "duration": 8, "estimated_credits": 180},
        {"model": "veo-3.1-quality", "duration": 8, "estimated_credits": 300},
        {"model": "veo-3-fast", "duration": 8, "estimated_credits": 140},
    ],
}

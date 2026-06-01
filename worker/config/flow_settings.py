from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

GenerationType = Literal["text_to_image", "image_to_image", "text_to_video", "image_to_video"]


class FlowGenerationSettings(BaseModel):
    model: str
    duration: int | None = Field(default=None, ge=1)
    estimated_credits: int = Field(default=0, ge=0)
    presets: dict[str, Any] = Field(default_factory=dict)


class FlowSettings(BaseModel):
    text_to_image: FlowGenerationSettings = Field(
        default_factory=lambda: FlowGenerationSettings(model="nano-banana-2", estimated_credits=20)
    )
    image_to_image: FlowGenerationSettings = Field(
        default_factory=lambda: FlowGenerationSettings(model="nano-banana-2-edit", estimated_credits=25)
    )
    text_to_video: FlowGenerationSettings = Field(
        default_factory=lambda: FlowGenerationSettings(model="veo-3.1-fast", duration=8, estimated_credits=160)
    )
    image_to_video: FlowGenerationSettings = Field(
        default_factory=lambda: FlowGenerationSettings(model="veo-3.1-quality", duration=8, estimated_credits=300)
    )


class FlowConfigManager:
    """Runtime-updatable global Google Flow generation configuration."""

    def __init__(self, config_path: Path, initial: FlowSettings | None = None) -> None:
        self.config_path = config_path
        self._settings = initial or FlowSettings()

    @classmethod
    def from_worker_config(cls, config_path: Path) -> "FlowConfigManager":
        config = _read_yaml(config_path)
        settings = FlowSettings.model_validate(config.get("flow_settings") or {})
        return cls(config_path=config_path, initial=settings)

    def snapshot(self) -> FlowSettings:
        return self._settings.model_copy(deep=True)

    def generation(self, generation_type: GenerationType) -> FlowGenerationSettings:
        return getattr(self._settings, generation_type).model_copy(deep=True)

    def generation_payload(self, generation_type: GenerationType) -> dict[str, Any]:
        settings = self.generation(generation_type).model_dump()
        settings["generation_type"] = generation_type
        return settings

    def patch(self, payload: dict[str, Any]) -> FlowSettings:
        current = self._settings.model_dump()
        updates = deepcopy(payload)
        for generation_type, value in updates.items():
            if generation_type not in current:
                raise ValueError(f"unknown flow settings section: {generation_type}")
            if not isinstance(value, dict):
                raise ValueError(f"{generation_type} must be an object")
            current[generation_type].update(value)
        self._settings = FlowSettings.model_validate(current)
        self._persist()
        return self.snapshot()

    def _persist(self) -> None:
        config = _read_yaml(self.config_path)
        config["flow_settings"] = self._settings.model_dump(exclude_none=True)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _read_yaml(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

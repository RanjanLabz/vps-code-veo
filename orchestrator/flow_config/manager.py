from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from orchestrator.config.settings import FlowGenerationSettings, FlowSettings
from orchestrator.queue.models import GenerationType


class FlowConfigManager:
    def __init__(self, config_path: Path, initial: FlowSettings) -> None:
        self.config_path = config_path
        self._settings = initial

    def snapshot(self) -> FlowSettings:
        return self._settings.model_copy(deep=True)

    def get_generation(self, generation_type: GenerationType) -> FlowGenerationSettings:
        return getattr(self._settings, generation_type).model_copy(deep=True)

    def resolve(self, generation_type: GenerationType, override: dict[str, Any] | None = None) -> dict[str, Any]:
        resolved = self.get_generation(generation_type).model_dump(exclude_none=True)
        if override:
            resolved.update(override)
        resolved["generation_type"] = generation_type
        return resolved

    def patch(self, payload: dict[str, Any]) -> FlowSettings:
        current = self._settings.model_dump()
        for section, update in deepcopy(payload).items():
            if section not in current:
                raise ValueError(f"unknown flow settings section: {section}")
            if not isinstance(update, dict):
                raise ValueError(f"{section} must be an object")
            current[section].update(update)
        self._settings = FlowSettings.model_validate(current)
        self._persist()
        return self.snapshot()

    def _persist(self) -> None:
        config = {}
        if self.config_path.exists():
            config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        config["flow_settings"] = self._settings.model_dump(exclude_none=True)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

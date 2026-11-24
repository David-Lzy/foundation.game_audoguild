from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from foundation_assistant.paths import PACKAGE_DIR


@dataclass(frozen=True)
class GameProfile:
    name: str
    window_title: str
    window_class: str
    base_width: int
    base_height: int
    data_dir: Path

    @property
    def actions_path(self) -> Path:
        return self.data_dir / "actions_1080p.yaml"

    @property
    def workflows_dir(self) -> Path:
        return self.data_dir / "workflows"

    @property
    def templates_dir(self) -> Path:
        return self.data_dir / "templates"

    @property
    def screens_path(self) -> Path:
        return self.data_dir / "screens_1080p.yaml"

    @property
    def template_requirements_path(self) -> Path:
        return self.data_dir / "template_requirements_1080p.yaml"


_PROFILES = {
    "foundation": GameProfile(
        name="foundation",
        window_title="Foundation: Galactic Frontier",
        window_class="UnityWndClass",
        base_width=1920,
        base_height=1080,
        data_dir=PACKAGE_DIR / "games" / "foundation" / "data",
    ),
}


def get_profile(name: str = "foundation") -> GameProfile:
    try:
        return _PROFILES[name]
    except KeyError as exc:
        known = ", ".join(sorted(_PROFILES))
        raise KeyError(f"Unknown game profile {name!r}. Known profiles: {known}") from exc


def list_profiles() -> list[GameProfile]:
    return [_PROFILES[name] for name in sorted(_PROFILES)]

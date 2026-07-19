from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class OutputFile(BaseModel):
    destination: Path
    steps: list[Any] = Field(default_factory=list)


class Outputs(BaseModel):
    vars: Optional[dict[str, Any]] = Field(default_factory=dict)
    files: list[OutputFile] = Field(default_factory=list)


class Source(BaseModel):
    # note: order is important here. Root must be first otherwise when
    # validating the other fields it won't be available yet
    root: Optional[Path] = None
    audio: dict[str, Path] = Field(default_factory=dict)
    markers: Path

    def with_root(self, filepath: str) -> Path:
        """Prepend root to the given filepath."""
        as_path = Path(filepath)
        if not self.root:
            return as_path
        if as_path.is_absolute():
            return as_path
        return self.root / as_path

    @field_validator("markers", "audio")
    def validate_path(cls, value: Path | dict[str, Path], info) -> Path:
        """Prepend root and ensure the path exists."""
        root = info.data.get("root")

        if isinstance(value, dict):
            for k, v in value.items():
                value[k] = root / v if root else v
            if not value[k].exists():
                raise FileNotFoundError(f"Path {value} does not exist.")
        else:
            value = root / value if root else value
            if not value.exists():
                raise FileNotFoundError(f"Path {value} does not exist.")

        return value


class Config(BaseModel):
    source: Source
    outputs: Outputs

    @classmethod
    def load(cls, path: Path) -> "Config":
        """Load the config from a file."""
        if not path.exists():
            raise FileNotFoundError(f"Config file {path} does not exist.")
        try:
            raw = yaml.safe_load(path.read_text())
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing config file: {e}")
        return cls.model_validate(raw)

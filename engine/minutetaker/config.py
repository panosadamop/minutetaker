"""Settings, data folder and secret handling."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

APP_NAME = "MinuteTaker"
SECRET_KEYS = ("anthropic_api_key", "openai_api_key", "hf_token")


def default_data_dir() -> Path:
    env = os.environ.get("MINUTETAKER_DATA")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


class Settings(BaseModel):
    # Speech-to-text
    stt_provider: Literal["local", "openai", "mock"] = "local"
    whisper_model: str = "auto"             # auto (base on CPU, small on GPU) | tiny | base | small | medium | large-v3
    whisper_device: str = "auto"            # auto | cpu | cuda
    language: str = "auto"                  # auto | el | en | ...
    # Diarization
    diarization: Literal["auto", "pyannote", "tracks"] = "auto"
    # LLM
    llm_provider: Literal["claude", "openai", "ollama", "mock"] = "claude"
    claude_model: str = "claude-sonnet-5-5"
    openai_model: str = "gpt-4.1"
    openai_stt_model: str = "whisper-1"
    ollama_model: str = "llama3.1"
    ollama_url: str = "http://localhost:11434"
    output_language: str = "same"           # same | el | en
    default_template: str = "formal"
    # Devices
    mic_device: Optional[str] = None
    system_device: Optional[str] = None
    # Storage / export
    retention_days: int = 0                 # 0 = keep audio forever
    company_name: str = ""
    logo_path: Optional[str] = None
    ui_language: Literal["en", "el"] = "en"
    custom_templates: dict[str, str] = Field(default_factory=dict)


class Config:
    """Holds settings + paths; persists to settings.json, secrets to keychain."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = Path(data_dir or default_data_dir())
        self.audio_dir = self.data_dir / "audio"
        self.export_dir = self.data_dir / "exports"
        for d in (self.data_dir, self.audio_dir, self.export_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.data_dir / "settings.json"
        self.db_path = self.data_dir / "minutetaker.db"
        self._fallback_secrets_path = self.data_dir / ".secrets.json"
        self.settings = self._load()

    # ---- settings -------------------------------------------------------
    def _load(self) -> Settings:
        if self.settings_path.exists():
            try:
                return Settings(**json.loads(self.settings_path.read_text("utf-8")))
            except Exception:
                pass
        return Settings()

    def save(self) -> None:
        self.settings_path.write_text(self.settings.model_dump_json(indent=2), "utf-8")

    def update(self, **values) -> Settings:
        data = self.settings.model_dump()
        data.update({k: v for k, v in values.items() if k in data})
        self.settings = Settings(**data)
        self.save()
        return self.settings

    # ---- secrets --------------------------------------------------------
    _ENV = {"anthropic_api_key": "ANTHROPIC_API_KEY",
            "openai_api_key": "OPENAI_API_KEY",
            "hf_token": "HF_TOKEN"}

    def get_secret(self, name: str) -> Optional[str]:
        env = os.environ.get(self._ENV.get(name, ""))
        if env:
            return env
        try:
            import keyring  # type: ignore
            val = keyring.get_password(APP_NAME, name)
            if val:
                return val
        except Exception:
            pass
        if self._fallback_secrets_path.exists():
            try:
                return json.loads(self._fallback_secrets_path.read_text()).get(name)
            except Exception:
                return None
        return None

    def set_secret(self, name: str, value: str) -> str:
        """Store a secret. Returns 'keychain' or 'file' (fallback when no keychain)."""
        if name not in SECRET_KEYS:
            raise ValueError(f"unknown secret {name}")
        try:
            import keyring  # type: ignore
            keyring.set_password(APP_NAME, name, value)
            return "keychain"
        except Exception:
            data = {}
            if self._fallback_secrets_path.exists():
                data = json.loads(self._fallback_secrets_path.read_text())
            data[name] = value
            self._fallback_secrets_path.write_text(json.dumps(data))
            try:
                os.chmod(self._fallback_secrets_path, 0o600)
            except Exception:
                pass
            return "file"

    def secret_status(self) -> dict[str, bool]:
        return {k: bool(self.get_secret(k)) for k in SECRET_KEYS}

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class WhisperLiveConfig(BaseSettings):
    host: str = "localhost"
    port: int = 9090
    ws_url: str = "ws://localhost:9090"
    uid: str = "c3f7a1b2-d4e5-6789-abcd-ef0123456789"
    language: str = "en"
    task: str = "transcribe"
    model: str = "base"
    use_vad: bool = True
    send_last_n_segments: int = 10

    class Config:
        env_prefix = "WHISPERLIVE_"


class AudioConfig(BaseSettings):
    input_mode: str = "microphone"
    device_index: int = -1
    device_name: Optional[str] = None
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 4096
    input_file: Optional[str] = None

    class Config:
        env_prefix = "AUDIO_"

    @property
    def bytes_per_chunk(self) -> int:
        return self.chunk_size * self.channels * 2


class ServerConfig(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"

    class Config:
        env_prefix = "SERVER_"


class AggregationConfig(BaseSettings):
    max_unconsolidated_segments: int = 1000
    max_consolidated_length: int = 100000
    max_questions: int = 500
    commit_delay_seconds: float = 2.0

    class Config:
        env_prefix = "AGGREGATION_"


class EnglishConfig(BaseSettings):
    enforce_english: bool = True
    min_english_confidence: float = 0.8

    class Config:
        env_prefix = "ENGLISH_"


class UIConfig(BaseSettings):
    enabled: bool = True

    class Config:
        env_prefix = "UI_"


class Settings(BaseSettings):
    whisperlive: WhisperLiveConfig = Field(default_factory=WhisperLiveConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    aggregation: AggregationConfig = Field(default_factory=AggregationConfig)
    english: EnglishConfig = Field(default_factory=EnglishConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    project_root: Path = Path(__file__).parent.parent.parent.parent

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "Settings":
        if env_file:
            env_path = Path(env_file)
            if env_path.exists():
                os.environ["DOTENV_FILE"] = str(env_path)
        return cls()

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings(env_file: Optional[str] = None) -> Settings:
    return Settings.from_env(env_file)

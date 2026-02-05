import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    whisperlive_host: str = "localhost"
    whisperlive_port: int = 9090
    whisperlive_ws_url: str = "ws://localhost:9090"
    whisperlive_uid: str = "c3f7a1b2-d4e5-6789-abcd-ef0123456789"
    whisperlive_language: str = "en"
    whisperlive_task: str = "transcribe"
    whisperlive_model: str = "base"
    whisperlive_use_vad: bool = True
    whisperlive_send_last_n_segments: int = 10
    whisperlive_audio_format: str = "float32"
    whisperlive_sample_rate: int = 16000
    whisperlive_channels: int = 1
    whisperlive_chunk_size: int = 4096

    audio_input_mode: str = "microphone"
    audio_device_index: int = -1
    audio_device_name: Optional[str] = None
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    audio_chunk_size: int = 4096
    audio_input_file: Optional[str] = None

    server_host: str = "0.0.0.0"
    server_port: int = 8001
    server_debug: bool = False
    server_log_level: str = "INFO"

    aggregation_max_unconsolidated_segments: int = 1000
    aggregation_max_consolidated_length: int = 100000
    aggregation_max_questions: int = 500
    aggregation_commit_delay_seconds: float = 2.0

    english_enforce: bool = True
    english_min_confidence: float = 0.8

    ui_enabled: bool = True

    project_root: Path = Path(__file__).parent.parent.parent.parent

    @property
    def audio_bytes_per_chunk(self) -> int:
        return self.audio_chunk_size * self.audio_channels * 2

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings(env_file: Optional[str] = None) -> Settings:
    if env_file:
        env_path = Path(env_file)
        if env_path.exists():
            os.environ["DOTENV_FILE"] = str(env_path)
    return Settings()

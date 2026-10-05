"""
config.py — Cấu hình chung cho tất cả Python Workers
Đọc từ biến môi trường (được inject bởi Docker Compose)
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # PostgreSQL
    postgres_dsn: str = os.getenv(
        "POSTGRES_DSN",
        "postgresql://vsuser:vspassword@localhost:5434/videosubtitle"
    )

    # RabbitMQ
    rabbitmq_url: str = os.getenv(
        "RABBITMQ_URL",
        "amqp://vsrabbit:vsrabbitpass@localhost:5672/"
    )

    # MinIO / S3
    minio_endpoint: str  = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "vsminio")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "vsminiopass")
    minio_bucket: str    = os.getenv("MINIO_BUCKET", "videos")
    minio_secure: bool   = os.getenv("MINIO_SECURE", "false").lower() == "true"

    # Whisper
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")   # tiny|base|small|medium|large-v3

    # Translation
    translation_provider: str      = os.getenv("TRANSLATION_PROVIDER", "google")
    google_translate_api_key: str  = os.getenv("GOOGLE_TRANSLATE_API_KEY", "")
    deepl_api_key: str             = os.getenv("DEEPL_API_KEY", "")
    gemini_api_key: str            = os.getenv("GEMINI_API_KEY", "")

    # C# API (để gọi callback)
    api_base_url: str = os.getenv("API_BASE_URL", "http://localhost:8080")

    # Worker settings
    tmp_dir: str       = os.getenv("TMP_DIR", "/tmp/vs_processing")
    prefetch_count: int = int(os.getenv("RABBITMQ_PREFETCH", "1"))  # Xử lý 1 job tại 1 thời điểm


# Queue names — phải khớp với C# RabbitMqService
class Queues:
    VIDEO_UPLOADED   = "video.uploaded"      # API → Worker 1
    AUDIO_EXTRACTED  = "audio.extracted"     # Worker 1 → Worker 2
    TRANSCRIPT_READY = "transcript.ready"    # Worker 2 → Worker 3
    TRANSLATION_DONE = "translation.ready"   # Worker 3 → Worker 4
    DEAD_LETTER      = "dead.letter"         # Errors


config = Config()

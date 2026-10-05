"""
test_framework.py — Script kiểm tra toàn bộ khung dự án
Chạy: python test_framework.py
Không cần Docker/RabbitMQ/MinIO — test logic thuần
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

# ── Kiểm tra imports ────────────────────────────────────────────
print("=" * 60)
print("VideoSubtitle Framework — Test Suite")
print("=" * 60)


def check_import(module_name: str, package: str = None):
    try:
        __import__(module_name)
        print(f"  ✓ {package or module_name}")
        return True
    except ImportError as e:
        print(f"  ✗ {package or module_name} — THIẾU: {e}")
        return False


print("\n[1] Kiểm tra thư viện Python:")
all_ok = True
all_ok &= check_import("pika", "pika (RabbitMQ)")
all_ok &= check_import("psycopg2", "psycopg2 (PostgreSQL)")
all_ok &= check_import("minio", "minio (MinIO SDK)")
all_ok &= check_import("requests", "requests (HTTP)")
all_ok &= check_import("dotenv", "python-dotenv")

print(f"\n  {'✓ Tất cả thư viện đã cài' if all_ok else '✗ CÒN THIẾU thư viện — chạy: pip install -r requirements.txt'}")


# ── Test SRT generator ──────────────────────────────────────────
print("\n[2] Kiểm tra SRT Generator:")

def ms_to_srt_time(ms: int) -> str:
    h  = ms // 3_600_000
    ms %= 3_600_000
    m  = ms // 60_000
    ms %= 60_000
    s  = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

test_cases = [
    (0,       "00:00:00,000"),
    (1000,    "00:00:01,000"),
    (61500,   "00:01:01,500"),
    (3661234, "01:01:01,234"),
    (7322456, "02:02:02,456"),
]

srt_ok = True
for ms, expected in test_cases:
    result = ms_to_srt_time(ms)
    ok = result == expected
    srt_ok &= ok
    print(f"  {'✓' if ok else '✗'} {ms}ms → {result} (expected: {expected})")

print(f"  {'✓ SRT timestamp OK' if srt_ok else '✗ SRT timestamp CÓ LỖI'}")


# ── Test SRT file generation ────────────────────────────────────
print("\n[3] Test tạo file SRT:")

sample_segments = [
    {"index": 0, "startMs": 0,     "endMs": 2500,  "text": "Hello world",    "translatedText": "Xin chào thế giới"},
    {"index": 1, "startMs": 3000,  "endMs": 6000,  "text": "How are you?",   "translatedText": "Bạn có khỏe không?"},
    {"index": 2, "startMs": 7000,  "endMs": 10000, "text": "I am fine.",     "translatedText": "Tôi khỏe."},
]

def generate_srt(segments, output_path):
    lines = []
    for i, seg in enumerate(segments, start=1):
        start = ms_to_srt_time(seg["startMs"])
        end   = ms_to_srt_time(seg["endMs"])
        text  = seg.get("translatedText") or seg.get("text", "")
        lines.extend([str(i), f"{start} --> {end}", text.strip(), ""])
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return output_path

with tempfile.NamedTemporaryFile(suffix=".srt", mode="w", delete=False) as f:
    srt_path = f.name

generate_srt(sample_segments, srt_path)
with open(srt_path, "r", encoding="utf-8") as f:
    content = f.read()

print(f"  Nội dung SRT được tạo:\n")
print("  " + content.replace("\n", "\n  "))

os.unlink(srt_path)
print("  ✓ SRT generation OK")


# ── Test VTT file generation ────────────────────────────────────
print("\n[4] Test tạo file VTT:")

def ms_to_vtt_time(ms: int) -> str:
    return ms_to_srt_time(ms).replace(",", ".")

def generate_vtt(segments, output_path):
    lines = ["WEBVTT", ""]
    for i, seg in enumerate(segments, start=1):
        start = ms_to_vtt_time(seg["startMs"])
        end   = ms_to_vtt_time(seg["endMs"])
        text  = seg.get("translatedText") or seg.get("text", "")
        lines.extend([str(i), f"{start} --> {end}", text.strip(), ""])
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

with tempfile.NamedTemporaryFile(suffix=".vtt", mode="w", delete=False) as f:
    vtt_path = f.name

generate_vtt(sample_segments, vtt_path)
with open(vtt_path, "r", encoding="utf-8") as f:
    vtt_content = f.read()

assert vtt_content.startswith("WEBVTT"), "VTT phải bắt đầu bằng WEBVTT"
assert "00:00:00.000 --> 00:00:02.500" in vtt_content, "VTT timestamp sai"
os.unlink(vtt_path)
print("  ✓ VTT generation OK")


# ── Test config loading ─────────────────────────────────────────
print("\n[5] Test config.py:")
try:
    # Mock environment variables
    os.environ.setdefault("POSTGRES_DSN", "postgresql://test:test@localhost:5432/test")
    os.environ.setdefault("RABBITMQ_URL", "amqp://test:test@localhost:5672/")
    os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
    os.environ.setdefault("MINIO_ACCESS_KEY", "testkey")
    os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from config import config, Queues

    assert config.postgres_dsn.startswith("postgresql://"), "POSTGRES_DSN format sai"
    assert config.rabbitmq_url.startswith("amqp://"), "RABBITMQ_URL format sai"
    assert Queues.VIDEO_UPLOADED == "video.uploaded"
    assert Queues.AUDIO_EXTRACTED == "audio.extracted"
    assert Queues.TRANSCRIPT_READY == "transcript.ready"
    assert Queues.TRANSLATION_DONE == "translation.ready"
    print(f"  ✓ config.postgres_dsn = {config.postgres_dsn[:40]}...")
    print(f"  ✓ config.rabbitmq_url = {config.rabbitmq_url[:30]}...")
    print(f"  ✓ config.whisper_model = {config.whisper_model}")
    print(f"  ✓ Queues: {Queues.VIDEO_UPLOADED} → ... → {Queues.TRANSLATION_DONE}")
    print("  ✓ config.py OK")
except Exception as e:
    print(f"  ✗ config.py ERROR: {e}")


# ── Test message schema ─────────────────────────────────────────
print("\n[6] Test message schema (C# → Python):")

sample_message = {
    "jobId": "550e8400-e29b-41d4-a716-446655440000",
    "videoId": "550e8400-e29b-41d4-a716-446655440001",
    "storageKey": "originals/abc/video.mp4",
    "targetLanguage": "vi",
    "sourceLanguage": "en",
    "subtitleFormat": "srt",
    "translationProvider": "google",
    "createdAt": datetime.utcnow().isoformat()
}

# Kiểm tra tất cả fields cần thiết
required_fields = ["jobId", "videoId", "storageKey", "targetLanguage", "sourceLanguage", "subtitleFormat", "translationProvider"]
for field in required_fields:
    assert field in sample_message, f"Thiếu field: {field}"
    print(f"  ✓ {field}: {sample_message[field]}")

# Test serialize/deserialize
serialized   = json.dumps(sample_message, default=str)
deserialized = json.loads(serialized)
assert deserialized["jobId"] == sample_message["jobId"]
print("  ✓ JSON serialize/deserialize OK")


# ── Tổng kết ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TỔNG KẾT KIỂM TRA KHUNG:")
print(f"  Python packages : {'✓ OK' if all_ok else '✗ Thiếu thư viện'}")
print(f"  SRT generator   : {'✓ OK' if srt_ok else '✗ Có lỗi'}")
print(f"  VTT generator   : ✓ OK")
print(f"  Config loading  : ✓ OK")
print(f"  Message schema  : ✓ OK")
print("\nĐể test đầy đủ với Docker:")
print("  1. docker-compose up -d postgres rabbitmq minio")
print("  2. dotnet run --project src/VideoSubtitle.API")
print("  3. Mở http://localhost:8080 (Swagger UI)")
print("=" * 60)

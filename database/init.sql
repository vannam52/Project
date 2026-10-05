-- ══════════════════════════════════════════════════════════════
-- VideoSubtitle Database Schema
-- ══════════════════════════════════════════════════════════════

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ──────────────────────────────────────────────────────────────
-- ENUM Types
-- ──────────────────────────────────────────────────────────────
CREATE TYPE job_status AS ENUM (
    'pending',          -- Vừa tạo, chờ xử lý
    'extracting_audio', -- Worker 1 đang tách audio
    'transcribing',     -- Worker 2 đang STT với Whisper
    'translating',      -- Worker 3 đang dịch
    'rendering',        -- Worker 4 đang ghép phụ đề
    'completed',        -- Xong xuôi
    'failed'            -- Thất bại
);

CREATE TYPE subtitle_format AS ENUM ('srt', 'vtt', 'ass');
CREATE TYPE translation_provider AS ENUM ('google', 'deepl', 'gemini', 'libre');

-- ──────────────────────────────────────────────────────────────
-- Table: videos
-- Lưu metadata của video gốc được upload
-- ──────────────────────────────────────────────────────────────
CREATE TABLE videos (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    original_name   VARCHAR(500) NOT NULL,              -- Tên file gốc
    storage_key     VARCHAR(1000) NOT NULL,              -- Key trên MinIO/S3
    file_size_bytes BIGINT NOT NULL,                    -- Kích thước file (bytes)
    duration_secs   FLOAT,                              -- Độ dài video (giây)
    mime_type       VARCHAR(100) DEFAULT 'video/mp4',
    source_language VARCHAR(10) NOT NULL DEFAULT 'auto', -- 'auto' = Whisper tự detect
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ──────────────────────────────────────────────────────────────
-- Table: translation_jobs
-- Mỗi video có thể có nhiều job dịch sang các ngôn ngữ khác nhau
-- ──────────────────────────────────────────────────────────────
CREATE TABLE translation_jobs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    video_id            UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    target_language     VARCHAR(10) NOT NULL,            -- 'vi', 'en', 'ja', 'ko', ...
    subtitle_format     subtitle_format NOT NULL DEFAULT 'srt',
    translation_provider translation_provider NOT NULL DEFAULT 'google',
    status              job_status NOT NULL DEFAULT 'pending',

    -- Kết quả
    output_video_key    VARCHAR(1000),                  -- Key video có phụ đề trên MinIO
    output_subtitle_key VARCHAR(1000),                  -- Key file .srt/.vtt trên MinIO
    error_message       TEXT,                           -- Nếu thất bại
    retry_count         INT NOT NULL DEFAULT 0,

    -- Thống kê
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    processing_secs     FLOAT,                          -- Tổng thời gian xử lý

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ──────────────────────────────────────────────────────────────
-- Table: job_steps
-- Lưu log chi tiết từng bước trong pipeline
-- ──────────────────────────────────────────────────────────────
CREATE TABLE job_steps (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id      UUID NOT NULL REFERENCES translation_jobs(id) ON DELETE CASCADE,
    step_name   VARCHAR(100) NOT NULL,   -- 'extract_audio', 'whisper_stt', 'translate', 'render'
    worker_name VARCHAR(100),            -- 'worker1', 'worker2', ...
    status      VARCHAR(50) NOT NULL DEFAULT 'running',  -- 'running' | 'done' | 'failed'
    log_message TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    -- FIX: unique constraint để worker upsert hoạt động
    UNIQUE (job_id, step_name)
);

-- ──────────────────────────────────────────────────────────────
-- Table: subtitle_segments
-- Lưu từng câu phụ đề (gốc + đã dịch) với timestamp
-- ──────────────────────────────────────────────────────────────
CREATE TABLE subtitle_segments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id          UUID NOT NULL REFERENCES translation_jobs(id) ON DELETE CASCADE,
    segment_index   INT NOT NULL,           -- Thứ tự câu (1, 2, 3, ...)
    start_time_ms   INT NOT NULL,           -- Thời gian bắt đầu (milliseconds)
    end_time_ms     INT NOT NULL,           -- Thời gian kết thúc (milliseconds)
    original_text   TEXT NOT NULL,          -- Văn bản gốc (từ Whisper)
    translated_text TEXT,                   -- Văn bản đã dịch
    confidence      FLOAT,                  -- Độ tin cậy của Whisper (0-1)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ──────────────────────────────────────────────────────────────
-- Indexes (tối ưu truy vấn)
-- ──────────────────────────────────────────────────────────────
CREATE INDEX idx_translation_jobs_video_id ON translation_jobs(video_id);
CREATE INDEX idx_translation_jobs_status ON translation_jobs(status);
CREATE INDEX idx_translation_jobs_created_at ON translation_jobs(created_at DESC);
CREATE INDEX idx_job_steps_job_id ON job_steps(job_id);
CREATE INDEX idx_subtitle_segments_job_id ON subtitle_segments(job_id);
CREATE INDEX idx_subtitle_segments_job_order ON subtitle_segments(job_id, segment_index);
-- Partial index: tìm nhanh jobs đang pending/chạy
CREATE INDEX idx_jobs_active ON translation_jobs(status) WHERE status NOT IN ('completed', 'failed');

-- ──────────────────────────────────────────────────────────────
-- Trigger: tự động cập nhật updated_at
-- ──────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_videos_updated_at
    BEFORE UPDATE ON videos
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_jobs_updated_at
    BEFORE UPDATE ON translation_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ──────────────────────────────────────────────────────────────
-- Sample data (để test)
-- ──────────────────────────────────────────────────────────────
INSERT INTO videos (id, original_name, storage_key, file_size_bytes, source_language)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'sample_video.mp4',
    'originals/sample_video.mp4',
    10485760,  -- 10MB
    'en'
);

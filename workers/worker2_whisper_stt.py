"""
worker2_whisper_stt.py
Lắng nghe queue: audio.extracted
Công việc: Tải audio.wav → chạy Whisper → trích xuất text + timestamp từng câu
Publish sang: transcript.ready
"""
import json
import os
from typing import Optional

try:
    import whisper
except ImportError:
    whisper = None

from config import Queues, config
from worker_base import BaseWorker


class WhisperSTTWorker(BaseWorker):

    def __init__(self):
        super().__init__(
            input_queue=Queues.AUDIO_EXTRACTED,
            output_queue=Queues.TRANSCRIPT_READY,
            worker_name="worker2_whisper_stt"
        )
        if whisper is None:
            raise RuntimeError(
                "Thư viện 'whisper' chưa được cài đặt trên môi trường hiện tại. "
                "Vui lòng cài đặt: pip install openai-whisper hoặc chạy worker thông qua Docker container."
            )
        # Load model một lần duy nhất khi khởi động (tránh reload mỗi request)
        self.logger.info(f"Loading Whisper model: '{config.whisper_model}'...")
        self.model = whisper.load_model(config.whisper_model)
        self.logger.info(f"Whisper model loaded ✓")

    def process_message(self, message: dict) -> Optional[dict]:
        job_id    = message["jobId"]
        audio_key = message["audioKey"]
        source_lang = message.get("sourceLanguage", "auto")

        # ── Bước 1: Cập nhật trạng thái ───────────────────────
        self.update_job_status(job_id, "transcribing")
        self.log_step(job_id, "whisper_stt", "running", f"Đang nhận diện giọng nói (model: {config.whisper_model})...")

        # ── Bước 2: Tải audio về máy ──────────────────────────
        job_dir    = os.path.join(config.tmp_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)
        audio_path = os.path.join(job_dir, "audio.wav")

        self.download_file(audio_key, audio_path)

        # ── Bước 3: Chạy Whisper ───────────────────────────────
        whisper_options = {
            "task": "transcribe",
            "verbose": False,
            "word_timestamps": False,   # True nếu muốn timestamp từng từ
        }

        # Chỉ set language nếu không phải auto-detect
        if source_lang != "auto":
            whisper_options["language"] = source_lang

        self.logger.info(f"Running Whisper transcription for job {job_id}...")
        result = self.model.transcribe(audio_path, **whisper_options)

        detected_language = result.get("language", "unknown")
        segments          = result.get("segments", [])

        self.logger.info(f"Detected language: {detected_language}, segments: {len(segments)}")

        # ── Bước 4: Lưu segments vào PostgreSQL ───────────────
        self._save_segments_to_db(job_id, segments)

        # ── Bước 5: Lưu transcript JSON lên MinIO ─────────────
        transcript_data = {
            "jobId": job_id,
            "detectedLanguage": detected_language,
            "segments": [
                {
                    "index": s["id"],
                    "startMs": int(s["start"] * 1000),
                    "endMs":   int(s["end"]   * 1000),
                    "text":    s["text"].strip(),
                    "avgLogprob": s.get("avg_logprob", 0.0),
                    "noSpeechProb": s.get("no_speech_prob", 0.0),
                }
                for s in segments
            ]
        }

        transcript_key  = f"transcripts/{job_id}/transcript.json"
        transcript_path = os.path.join(job_dir, "transcript.json")

        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(transcript_data, f, ensure_ascii=False, indent=2)

        self.upload_file(transcript_path, transcript_key, "application/json")

        # Dọn dẹp audio (đã xong nhiệm vụ)
        os.remove(audio_path)

        self.finish_step(job_id, "whisper_stt", "done")
        self.logger.info(f"Transcription done: {len(segments)} segments")

        # ── Publish sang Worker 3 (Dịch thuật) ────────────────
        return {
            **message,
            "transcriptKey":     transcript_key,
            "detectedLanguage":  detected_language,
            "segmentCount":      len(segments)
        }

    def _save_segments_to_db(self, job_id: str, segments: list):
        """Lưu tất cả segments vào bảng subtitle_segments"""
        with self._get_db_conn() as conn:
            with conn.cursor() as cur:
                # Xóa segments cũ nếu có (retry case)
                cur.execute("DELETE FROM subtitle_segments WHERE job_id = %s", (job_id,))

                for seg in segments:
                    # Confidence = e^(avg_logprob), clamp [0, 1]
                    confidence = min(1.0, max(0.0, pow(2.71828, seg.get("avg_logprob", -1.0))))

                    cur.execute(
                        """INSERT INTO subtitle_segments
                           (job_id, segment_index, start_time_ms, end_time_ms, original_text, confidence)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (
                            job_id,
                            seg["id"],
                            int(seg["start"] * 1000),
                            int(seg["end"]   * 1000),
                            seg["text"].strip(),
                            confidence
                        )
                    )
            conn.commit()


if __name__ == "__main__":
    WhisperSTTWorker().run()

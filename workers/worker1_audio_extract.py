"""
worker1_audio_extract.py
Lắng nghe queue: video.uploaded
Công việc: Tải video từ MinIO → tách audio bằng FFmpeg → upload audio.wav lên MinIO
Publish sang: audio.extracted
"""
import os
import subprocess

from config import Queues, config
from worker_base import BaseWorker


class AudioExtractWorker(BaseWorker):

    def __init__(self):
        super().__init__(
            input_queue=Queues.VIDEO_UPLOADED,
            output_queue=Queues.AUDIO_EXTRACTED,
            worker_name="worker1_audio_extract"
        )

    def process_message(self, message: dict) -> dict | None:
        job_id      = message["jobId"]
        video_id    = message["videoId"]
        storage_key = message["storageKey"]

        # ── Bước 1: Cập nhật DB và log ────────────────────────
        self.update_job_status(job_id, "extracting_audio")
        self.log_step(job_id, "extract_audio", "running", "Đang tải video từ MinIO...")

        # ── Bước 2: Tải video về máy tạm ──────────────────────
        job_dir    = os.path.join(config.tmp_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)

        video_path = os.path.join(job_dir, "input_video.mp4")
        audio_path = os.path.join(job_dir, "audio.wav")

        self.download_file(storage_key, video_path)
        self.logger.info(f"Video downloaded: {video_path} ({os.path.getsize(video_path)} bytes)")

        # ── Bước 3: Lấy thông tin độ dài video ────────────────
        duration_secs = self._get_video_duration(video_path)
        self._update_video_duration(video_id, duration_secs)

        # ── Bước 4: Tách audio bằng FFmpeg ────────────────────
        self.log_step(job_id, "extract_audio", "running", f"Đang tách audio (duration: {duration_secs:.1f}s)...")
        self._extract_audio(video_path, audio_path)

        # ── Bước 5: Upload audio.wav lên MinIO ────────────────
        audio_key = f"audio/{job_id}/audio.wav"
        self.upload_file(audio_path, audio_key, "audio/wav")

        # Dọn file video tạm để tiết kiệm disk
        os.remove(video_path)

        self.finish_step(job_id, "extract_audio", "done")
        self.logger.info(f"Audio extracted: {audio_key}")

        # ── Publish sang Worker 2 (Whisper STT) ───────────────
        return {
            **message,              # Giữ nguyên toàn bộ metadata gốc
            "audioKey": audio_key,
            "durationSecs": duration_secs
        }

    def _extract_audio(self, video_path: str, audio_path: str):
        """
        Dùng FFmpeg tách audio thành WAV 16kHz mono (định dạng Whisper cần)
        """
        cmd = [
            "ffmpeg", "-y",             # -y: overwrite nếu đã tồn tại
            "-i", video_path,           # Input video
            "-vn",                      # Bỏ luồng video
            "-acodec", "pcm_s16le",     # PCM 16-bit little-endian
            "-ar", "16000",             # 16kHz sample rate (Whisper yêu cầu)
            "-ac", "1",                 # Mono channel
            audio_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")

        self.logger.info(f"FFmpeg audio extraction complete")

    def _get_video_duration(self, video_path: str) -> float:
        """Lấy độ dài video (giây) bằng ffprobe"""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 0.0

    def _update_video_duration(self, video_id: str, duration_secs: float):
        """Cập nhật độ dài vào bảng videos"""
        with self._get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE videos SET duration_secs = %s WHERE id = %s",
                    (duration_secs, video_id)
                )
            conn.commit()


if __name__ == "__main__":
    AudioExtractWorker().run()

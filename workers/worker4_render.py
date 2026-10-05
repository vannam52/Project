"""
worker4_render.py
Lắng nghe queue: translation.ready
Công việc:
  1. Tạo file .srt hoặc .vtt từ segments đã dịch
  2. Dùng FFmpeg burn-in phụ đề vào video (hardcode)
  3. Upload kết quả lên MinIO
  4. Cập nhật DB "completed" + gọi callback về C# API
Đây là bước cuối của pipeline.
"""
import json
import os
import subprocess

from config import Queues, config
from worker_base import BaseWorker


class RenderWorker(BaseWorker):

    def __init__(self):
        super().__init__(
            input_queue=Queues.TRANSLATION_DONE,
            output_queue=None,  # Pipeline kết thúc tại đây
            worker_name="worker4_render"
        )

    def process_message(self, message: dict) -> dict | None:
        job_id          = message["jobId"]
        video_id        = message["videoId"]
        original_key    = message["storageKey"]     # Video gốc
        translation_key = message["translationKey"]
        subtitle_fmt    = message.get("subtitleFormat", "srt").lower()
        target_lang     = message["targetLanguage"]

        # ── Bước 1: Cập nhật trạng thái ───────────────────────
        self.update_job_status(job_id, "rendering")
        self.log_step(job_id, "render", "running", "Đang tạo phụ đề và ghép vào video...")

        # ── Bước 2: Tải files cần thiết ───────────────────────
        job_dir        = os.path.join(config.tmp_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)

        video_path       = os.path.join(job_dir, "input_video.mp4")
        translation_path = os.path.join(job_dir, "translated.json")

        self.download_file(original_key, video_path)
        self.download_file(translation_key, translation_path)

        with open(translation_path, "r", encoding="utf-8") as f:
            translation = json.load(f)

        segments = translation["segments"]

        # ── Bước 3: Tạo file phụ đề ───────────────────────────
        subtitle_path = os.path.join(job_dir, f"subtitle.{subtitle_fmt}")

        if subtitle_fmt == "srt":
            self._generate_srt(segments, subtitle_path)
        elif subtitle_fmt == "vtt":
            self._generate_vtt(segments, subtitle_path)
        else:
            self._generate_srt(segments, subtitle_path)  # fallback

        self.logger.info(f"Subtitle file created: {subtitle_path}")

        # ── Bước 4: FFmpeg ghép phụ đề vào video ──────────────
        output_video_path = os.path.join(job_dir, "output_video.mp4")
        self._burn_subtitles(video_path, subtitle_path, output_video_path)

        # ── Bước 5: Upload kết quả lên MinIO ──────────────────
        output_video_key    = f"outputs/{job_id}/video_{target_lang}.mp4"
        output_subtitle_key = f"outputs/{job_id}/subtitle_{target_lang}.{subtitle_fmt}"

        self.upload_file(output_video_path, output_video_key, "video/mp4")
        self.upload_file(subtitle_path, output_subtitle_key, "text/plain")

        # ── Bước 6: Lưu kết quả vào DB ────────────────────────
        self._update_job_completed(job_id, output_video_key, output_subtitle_key)
        self.finish_step(job_id, "render", "done")

        # Dọn dẹp toàn bộ file tạm
        self._cleanup_job_dir(job_dir)

        # ── Bước 7: Gọi C# API callback → trigger SignalR ─────
        self.notify_api(
            job_id=job_id,
            status="completed",
            output_video_key=output_video_key,
            output_subtitle_key=output_subtitle_key
        )

        self.logger.info(f"Job {job_id} COMPLETED ✓ → {output_video_key}")
        return None  # Pipeline kết thúc

    # ── Subtitle generators ────────────────────────────────────

    def _generate_srt(self, segments: list, output_path: str):
        """Tạo file .SRT chuẩn"""
        lines = []
        for i, seg in enumerate(segments, start=1):
            start = self._ms_to_srt_time(seg["startMs"])
            end   = self._ms_to_srt_time(seg["endMs"])
            text  = seg.get("translatedText") or seg.get("text", "")

            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text.strip())
            lines.append("")  # Dòng trống phân cách

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _generate_vtt(self, segments: list, output_path: str):
        """Tạo file .VTT (WebVTT - chuẩn web)"""
        lines = ["WEBVTT", ""]
        for i, seg in enumerate(segments, start=1):
            start = self._ms_to_vtt_time(seg["startMs"])
            end   = self._ms_to_vtt_time(seg["endMs"])
            text  = seg.get("translatedText") or seg.get("text", "")

            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text.strip())
            lines.append("")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _ms_to_srt_time(self, ms: int) -> str:
        """Chuyển milliseconds → SRT format: HH:MM:SS,mmm"""
        h  = ms // 3_600_000
        ms %= 3_600_000
        m  = ms // 60_000
        ms %= 60_000
        s  = ms // 1000
        ms %= 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _ms_to_vtt_time(self, ms: int) -> str:
        """Chuyển milliseconds → VTT format: HH:MM:SS.mmm"""
        return self._ms_to_srt_time(ms).replace(",", ".")

    # ── FFmpeg render ──────────────────────────────────────────

    def _burn_subtitles(self, video_path: str, subtitle_path: str, output_path: str):
        """
        Dùng FFmpeg burn-in (hardcode) phụ đề vào video.
        Phụ đề sẽ hiển thị vĩnh viễn, không tắt được.
        Nếu muốn softsub (phụ đề mềm), dùng lệnh thứ 2 bên dưới.
        """
        # Escape path cho FFmpeg filter
        escaped_sub = subtitle_path.replace("\\", "/").replace(":", "\\:")

        # Option 1: Burn-in (hardcode) — phụ đề cứng trên video
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles='{escaped_sub}':force_style='FontSize=18,PrimaryColour=&HFFFFFF&'",
            "-c:a", "copy",   # Giữ nguyên audio, không encode lại
            "-preset", "fast", # Cân bằng tốc độ/chất lượng
            output_path
        ]

        # Option 2: Softsub — đính kèm file phụ đề, user có thể tắt/mở
        # cmd = [
        #     "ffmpeg", "-y",
        #     "-i", video_path,
        #     "-i", subtitle_path,
        #     "-c", "copy",
        #     "-c:s", "mov_text",  # mp4 subtitle codec
        #     output_path
        # ]

        self.logger.info(f"Running FFmpeg render...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg render failed:\n{result.stderr[-2000:]}")

        self.logger.info(f"FFmpeg render complete: {output_path}")

    # ── Helpers ────────────────────────────────────────────────

    def _update_job_completed(self, job_id: str, video_key: str, subtitle_key: str):
        """Lưu output keys và đánh dấu completed"""
        with self._get_db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE translation_jobs
                       SET status = 'completed'::job_status,
                           output_video_key = %s,
                           output_subtitle_key = %s,
                           completed_at = NOW(),
                           processing_secs = EXTRACT(EPOCH FROM (NOW() - started_at)),
                           updated_at = NOW()
                       WHERE id = %s""",
                    (video_key, subtitle_key, job_id)
                )
            conn.commit()

    def _cleanup_job_dir(self, job_dir: str):
        """Xóa toàn bộ file tạm"""
        import shutil
        try:
            shutil.rmtree(job_dir)
            self.logger.info(f"Cleaned up temp dir: {job_dir}")
        except Exception as e:
            self.logger.warning(f"Cleanup failed: {e}")


if __name__ == "__main__":
    RenderWorker().run()

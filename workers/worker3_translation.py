"""
worker3_translation.py
Lắng nghe queue: transcript.ready
Công việc: Tải transcript.json → dịch từng segment → lưu kết quả
Publish sang: translation.ready

Hỗ trợ providers: google | deepl | gemini | libre (offline)
"""
import json
import os
import time

import requests

from config import Queues, config
from worker_base import BaseWorker


class TranslationWorker(BaseWorker):

    def __init__(self):
        super().__init__(
            input_queue=Queues.TRANSCRIPT_READY,
            output_queue=Queues.TRANSLATION_DONE,
            worker_name="worker3_translation"
        )
        self.logger.info(f"Translation provider: {config.translation_provider}")

    def process_message(self, message: dict) -> dict | None:
        job_id         = message["jobId"]
        transcript_key = message["transcriptKey"]
        target_lang    = message["targetLanguage"]
        source_lang    = message.get("detectedLanguage", "auto")
        provider       = message.get("translationProvider", config.translation_provider)

        # ── Bước 1: Cập nhật trạng thái ───────────────────────
        self.update_job_status(job_id, "translating")
        self.log_step(job_id, "translation", "running",
                      f"Đang dịch sang {target_lang} bằng {provider}...")

        # ── Bước 2: Tải transcript ─────────────────────────────
        job_dir         = os.path.join(config.tmp_dir, job_id)
        os.makedirs(job_dir, exist_ok=True)
        transcript_path = os.path.join(job_dir, "transcript.json")

        self.download_file(transcript_key, transcript_path)

        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = json.load(f)

        segments = transcript["segments"]
        self.logger.info(f"Translating {len(segments)} segments ({source_lang} → {target_lang})")

        # ── Bước 3: Dịch từng segment ─────────────────────────
        translated_segments = []
        for i, seg in enumerate(segments):
            original_text = seg["text"]

            # Bỏ qua nếu text rỗng
            if not original_text.strip():
                seg["translatedText"] = ""
                translated_segments.append(seg)
                continue

            translated_text = self._translate(original_text, source_lang, target_lang, provider)
            seg["translatedText"] = translated_text
            translated_segments.append(seg)

            # Rate limiting — tránh bị block API
            if (i + 1) % 10 == 0:
                self.logger.info(f"Translated {i+1}/{len(segments)} segments...")
                time.sleep(0.5)

        # ── Bước 4: Lưu segments đã dịch vào DB ───────────────
        self._update_translations_in_db(job_id, translated_segments)

        # ── Bước 5: Lưu translation JSON lên MinIO ────────────
        translation_data = {**transcript, "segments": translated_segments, "targetLanguage": target_lang}
        translation_key  = f"translations/{job_id}/translated.json"
        translation_path = os.path.join(job_dir, "translated.json")

        with open(translation_path, "w", encoding="utf-8") as f:
            json.dump(translation_data, f, ensure_ascii=False, indent=2)

        self.upload_file(translation_path, translation_key, "application/json")

        self.finish_step(job_id, "translation", "done")
        self.logger.info(f"Translation complete: {len(translated_segments)} segments")

        # ── Publish sang Worker 4 (Render) ─────────────────────
        return {
            **message,
            "translationKey": translation_key,
        }

    # ── Translation Providers ──────────────────────────────────

    def _translate(self, text: str, source_lang: str, target_lang: str, provider: str) -> str:
        """Gọi provider tương ứng để dịch"""
        try:
            if provider == "google":
                return self._translate_google(text, source_lang, target_lang)
            elif provider == "deepl":
                return self._translate_deepl(text, source_lang, target_lang)
            elif provider == "gemini":
                return self._translate_gemini(text, source_lang, target_lang)
            elif provider == "libre":
                return self._translate_libre(text, source_lang, target_lang)
            else:
                raise ValueError(f"Unknown provider: {provider}")
        except Exception as e:
            self.logger.warning(f"Translation failed for '{text[:50]}...': {e}")
            return text  # Fallback: giữ nguyên text gốc

    def _translate_google(self, text: str, source: str, target: str) -> str:
        """Google Cloud Translation API v2 (Basic)"""
        url = "https://translation.googleapis.com/language/translate/v2"
        resp = requests.post(url, params={"key": config.google_translate_api_key}, json={
            "q": text,
            "source": "auto" if source == "auto" else source,
            "target": target,
            "format": "text"
        }, timeout=30)
        resp.raise_for_status()
        return resp.json()["data"]["translations"][0]["translatedText"]

    def _translate_deepl(self, text: str, source: str, target: str) -> str:
        """DeepL API (Free tier có sẵn)"""
        url = "https://api-free.deepl.com/v2/translate"
        resp = requests.post(url, headers={"Authorization": f"DeepL-Auth-Key {config.deepl_api_key}"}, data={
            "text": text,
            "source_lang": None if source == "auto" else source.upper(),
            "target_lang": target.upper()
        }, timeout=30)
        resp.raise_for_status()
        return resp.json()["translations"][0]["text"]

    def _translate_gemini(self, text: str, source: str, target: str) -> str:
        """Google Gemini API (Generative AI)"""
        import google.generativeai as genai
        genai.configure(api_key=config.gemini_api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = (
            f"Translate the following subtitle text from {source} to {target}.\n"
            f"Rules: Keep timing markers intact, preserve tone, return ONLY the translation.\n\n"
            f"Text: {text}"
        )
        response = model.generate_content(prompt)
        return response.text.strip()

    def _translate_libre(self, text: str, source: str, target: str) -> str:
        """LibreTranslate — có thể tự host miễn phí"""
        url = os.getenv("LIBRETRANSLATE_URL", "https://libretranslate.com/translate")
        resp = requests.post(url, json={
            "q": text,
            "source": "auto" if source == "auto" else source,
            "target": target,
            "format": "text"
        }, timeout=30)
        resp.raise_for_status()
        return resp.json()["translatedText"]

    # ── Database ───────────────────────────────────────────────

    def _update_translations_in_db(self, job_id: str, segments: list):
        """Cập nhật translated_text cho từng segment"""
        with self._get_db_conn() as conn:
            with conn.cursor() as cur:
                for seg in segments:
                    cur.execute(
                        """UPDATE subtitle_segments
                           SET translated_text = %s
                           WHERE job_id = %s AND segment_index = %s""",
                        (seg.get("translatedText"), job_id, seg["index"])
                    )
            conn.commit()


if __name__ == "__main__":
    TranslationWorker().run()

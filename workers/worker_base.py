"""
worker_base.py — Base class cho tất cả Python Workers
FIX LOG:
- Sửa log_step: dùng INSERT ... ON CONFLICT (job_id, step_name) DO UPDATE
- Sửa psycopg2 context manager: dùng try/except/finally rõ ràng
- Sửa _connect_rabbitmq: khai báo DLX trước khi khai báo queues
- Thêm ensure_bucket() khi kết nối MinIO
- Sửa kiểu hint Python 3.9 compatible (Union thay | )
"""
import json
import logging
import os
import time
import traceback
from abc import ABC, abstractmethod
from typing import Optional

import pika
import psycopg2
import psycopg2.extras
import requests
from minio import Minio

from config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


class BaseWorker(ABC):
    """
    Base class cho mọi worker trong pipeline.
    Subclass chỉ cần implement: process_message()
    """

    def __init__(self, input_queue: str, output_queue: Optional[str], worker_name: str):
        self.input_queue  = input_queue
        self.output_queue = output_queue
        self.worker_name  = worker_name
        self.logger = logging.getLogger(worker_name)

        os.makedirs(config.tmp_dir, exist_ok=True)
        self._minio = self._connect_minio()
        self._rabbitmq_conn, self._channel = self._connect_rabbitmq()
        self.logger.info(f"Worker '{worker_name}' started. Listening on: {input_queue}")

    # ── Kết nối ────────────────────────────────────────────────

    def _connect_minio(self) -> Minio:
        client = Minio(
            endpoint=config.minio_endpoint,
            access_key=config.minio_access_key,
            secret_key=config.minio_secret_key,
            secure=config.minio_secure
        )
        # Tạo bucket nếu chưa tồn tại
        if not client.bucket_exists(config.minio_bucket):
            client.make_bucket(config.minio_bucket)
            self.logger.info(f"Created MinIO bucket: {config.minio_bucket}")
        return client

    def _connect_rabbitmq(self):
        """Kết nối RabbitMQ với retry"""
        params = pika.URLParameters(config.rabbitmq_url)
        params.heartbeat = 600
        params.blocked_connection_timeout = 300

        for attempt in range(10):
            try:
                conn    = pika.BlockingConnection(params)
                channel = conn.channel()

                # FIX: Khai báo DLX TRƯỚC khi khai báo queues có x-dead-letter-exchange
                channel.exchange_declare(exchange="dlx", exchange_type="direct", durable=True)
                channel.queue_declare(queue="dead.letter", durable=True)
                channel.queue_bind(queue="dead.letter", exchange="dlx", routing_key="dead.letter")

                dead_args = {
                    "x-dead-letter-exchange": "dlx",
                    "x-dead-letter-routing-key": "dead.letter",
                    "x-message-ttl": 86400000  # 24h
                }
                for q in ["video.uploaded", "audio.extracted", "transcript.ready", "translation.ready"]:
                    channel.queue_declare(queue=q, durable=True, arguments=dead_args)

                channel.basic_qos(prefetch_count=config.prefetch_count)
                self.logger.info("Connected to RabbitMQ ✓")
                return conn, channel

            except Exception as e:
                self.logger.warning(f"RabbitMQ not ready (attempt {attempt+1}/10): {e}")
                time.sleep(5)

        raise RuntimeError("Cannot connect to RabbitMQ after 10 attempts")

    # ── DB helper với explicit transaction ─────────────────────

    def _get_db_conn(self):
        """Kết nối PostgreSQL mới (caller chịu trách nhiệm đóng)"""
        return psycopg2.connect(config.postgres_dsn, cursor_factory=psycopg2.extras.RealDictCursor)

    def _db_execute(self, sql: str, params: tuple):
        """Helper: chạy 1 câu UPDATE/INSERT và commit"""
        conn = self._get_db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── MinIO helpers ──────────────────────────────────────────

    def download_file(self, storage_key: str, local_path: str) -> str:
        self.logger.info(f"Downloading {storage_key} → {local_path}")
        self._minio.fget_object(config.minio_bucket, storage_key, local_path)
        return local_path

    def upload_file(self, local_path: str, storage_key: str, content_type: str = "application/octet-stream") -> str:
        self.logger.info(f"Uploading {local_path} → {storage_key}")
        self._minio.fput_object(config.minio_bucket, storage_key, local_path, content_type=content_type)
        return storage_key

    # ── Database helpers ───────────────────────────────────────

    def update_job_status(self, job_id: str, status: str, error_msg: Optional[str] = None):
        self._db_execute(
            """UPDATE translation_jobs
               SET status = %s::job_status, error_message = %s, updated_at = NOW()
               WHERE id = %s::uuid""",
            (status, error_msg, job_id)
        )

    def log_step(self, job_id: str, step_name: str, status: str, log_message: Optional[str] = None):
        """
        FIX: Thêm unique constraint-based upsert thay vì ON CONFLICT DO NOTHING
        (job_id, step_name) là pair duy nhất cho mỗi lần chạy
        """
        self._db_execute(
            """INSERT INTO job_steps (job_id, step_name, worker_name, status, log_message, started_at)
               VALUES (%s::uuid, %s, %s, %s, %s, NOW())
               ON CONFLICT (job_id, step_name)
               DO UPDATE SET status = EXCLUDED.status,
                             log_message = EXCLUDED.log_message,
                             started_at = NOW()""",
            (job_id, step_name, self.worker_name, status, log_message)
        )

    def finish_step(self, job_id: str, step_name: str, status: str = "done"):
        self._db_execute(
            """UPDATE job_steps
               SET status = %s, finished_at = NOW()
               WHERE job_id = %s::uuid AND step_name = %s""",
            (status, job_id, step_name)
        )

    # ── API Callback (C# → SignalR) ────────────────────────────

    def notify_api(self, job_id: str, status: str,
                   output_video_key: Optional[str] = None,
                   output_subtitle_key: Optional[str] = None,
                   error_message: Optional[str] = None):
        try:
            resp = requests.post(
                f"{config.api_base_url}/api/jobs/{job_id}/callback",
                json={
                    "status": status,
                    "outputVideoKey": output_video_key,
                    "outputSubtitleKey": output_subtitle_key,
                    "errorMessage": error_message
                },
                timeout=10
            )
            resp.raise_for_status()
        except Exception as e:
            self.logger.warning(f"Failed to notify API (non-fatal): {e}")

    # ── Publish to next queue ──────────────────────────────────

    def publish_next(self, message: dict):
        if not self.output_queue:
            return
        body  = json.dumps(message, default=str).encode()
        props = pika.BasicProperties(delivery_mode=2, content_type="application/json")
        self._channel.basic_publish(
            exchange="",
            routing_key=self.output_queue,
            properties=props,
            body=body
        )
        self.logger.info(f"→ Published to {self.output_queue}: job {message.get('jobId','?')}")

    # ── Message handler ────────────────────────────────────────

    @abstractmethod
    def process_message(self, message: dict) -> Optional[dict]:
        """
        Implement logic xử lý tại đây.
        Return dict để publish sang queue tiếp theo, hoặc None nếu pipeline kết thúc.
        """
        ...

    def _on_message(self, channel, method, properties, body):
        message = {}
        job_id  = "unknown"
        try:
            message = json.loads(body)
            job_id  = message.get("jobId", "unknown")
            self.logger.info(f"▶ Processing job {job_id}")

            result = self.process_message(message)
            if result:
                self.publish_next(result)

            channel.basic_ack(delivery_tag=method.delivery_tag)
            self.logger.info(f"✓ Job {job_id} done")

        except Exception as e:
            self.logger.error(f"✗ Job {job_id} failed: {e}\n{traceback.format_exc()}")
            try:
                self.update_job_status(job_id, "failed", str(e)[:500])
                self.notify_api(job_id, "failed", error_message=str(e)[:500])
            except Exception as inner:
                self.logger.error(f"Error during error handling: {inner}")
            # NACK → Dead Letter Queue
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def run(self):
        self._channel.basic_consume(queue=self.input_queue, on_message_callback=self._on_message)
        self.logger.info(f"⏳ Waiting for messages on '{self.input_queue}'...")
        try:
            self._channel.start_consuming()
        except KeyboardInterrupt:
            self.logger.info("Worker stopping...")
            self._channel.stop_consuming()
        finally:
            if self._rabbitmq_conn and self._rabbitmq_conn.is_open:
                self._rabbitmq_conn.close()

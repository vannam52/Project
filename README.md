# 🎬 VideoSubtitle — Hệ thống Dịch thuật & Ghép Phụ đề Video Tự động

Hệ thống xử lý pipeline bất đồng bộ (async) để tự động:
1. Nhận diện giọng nói từ video (**Whisper AI**)
2. Dịch phụ đề sang ngôn ngữ đích
3. Ghép phụ đề vào video bằng **FFmpeg**
4. Thông báo real-time về browser qua **SignalR**

---

## 🏗️ Kiến trúc

```
User Browser
    │ upload video
    ▼
C# ASP.NET Core API (port 8080)
    │ lưu MinIO, ghi DB, push RabbitMQ
    ▼
RabbitMQ Queue: video.uploaded
    │
    ▼
Worker 1 — Audio Extract (Python + FFmpeg)
    │ audio.extracted
    ▼
Worker 2 — Whisper STT (Python + OpenAI Whisper)
    │ transcript.ready
    ▼
Worker 3 — Translation (Python + Google/DeepL/Gemini)
    │ translation.ready
    ▼
Worker 4 — Render (Python + FFmpeg)
    │ gọi callback → API → SignalR
    ▼
User Browser nhận notification "Video đã xong!"
```

---

## 📁 Cấu trúc Dự án

```
Project/
├── docker-compose.yml          # Toàn bộ stack
├── .env.example                # Template cấu hình
├── .gitignore
├── database/
│   └── init.sql                # Schema PostgreSQL
├── src/
│   └── VideoSubtitle.API/      # C# ASP.NET Core
│       ├── Controllers/
│       │   ├── VideosController.cs   # Upload, list, delete
│       │   └── JobsController.cs     # Status, segments, download
│       ├── Data/
│       │   └── AppDbContext.cs       # EF Core DbContext
│       ├── DTOs/
│       │   └── VideoDTOs.cs          # Request/Response models
│       ├── Hubs/
│       │   └── JobHub.cs             # SignalR real-time hub
│       ├── Models/
│       │   ├── Entities.cs           # DB entities
│       │   └── Enums.cs              # JobStatus, Format, Provider
│       ├── Services/
│       │   ├── StorageService.cs     # MinIO operations
│       │   └── MessageQueueService.cs # RabbitMQ publish
│       ├── Program.cs
│       ├── appsettings.json
│       └── Dockerfile
└── workers/                    # Python Workers
    ├── config.py               # Shared configuration
    ├── worker_base.py          # Base class (RabbitMQ, MinIO, DB)
    ├── worker1_audio_extract.py
    ├── worker2_whisper_stt.py
    ├── worker3_translation.py
    ├── worker4_render.py
    ├── requirements.txt
    └── Dockerfile
```

---

## 🚀 Khởi chạy (Quick Start)

### Prerequisites
- Docker Desktop đang chạy
- (Optional) GPU NVIDIA + CUDA nếu muốn Whisper nhanh hơn

### 1. Setup môi trường

```bash
cp .env.example .env
# Mở .env và điền API keys (Google Translate, DeepL, ...)
```

### 2. Chạy toàn bộ stack

```bash
docker-compose up -d
```

### 3. Kiểm tra health

```bash
# API Swagger UI
open http://localhost:8080

# RabbitMQ Management
open http://localhost:15672   # user: vsrabbit / vsrabbitpass

# MinIO Console
open http://localhost:9001    # user: vsminio / vsminiopass
```

### 4. Test pipeline

```bash
# Upload video
curl -X POST http://localhost:8080/api/videos/upload \
  -F "file=@my_video.mp4" \
  -F "targetLanguage=vi" \
  -F "translationProvider=google"

# Kết quả trả về:
# { "jobId": "xxx", "statusCheckUrl": "/api/jobs/xxx/status" }

# Kiểm tra trạng thái
curl http://localhost:8080/api/jobs/{jobId}/status
```

---

## 🛠️ Phát triển Local (không dùng Docker)

### C# API

```bash
cd src/VideoSubtitle.API
dotnet run
# → http://localhost:8080
```

### Python Workers (chạy riêng từng worker)

```bash
cd workers
pip install -r requirements.txt

python worker1_audio_extract.py  # Terminal 1
python worker2_whisper_stt.py    # Terminal 2
python worker3_translation.py    # Terminal 3
python worker4_render.py         # Terminal 4
```

---

## 📡 API Endpoints

| Method | Path | Mô tả |
|--------|------|-------|
| `POST` | `/api/videos/upload` | Upload video, bắt đầu pipeline |
| `GET`  | `/api/videos` | Danh sách video (phân trang) |
| `GET`  | `/api/videos/{id}` | Chi tiết video |
| `DELETE` | `/api/videos/{id}` | Xóa video |
| `GET`  | `/api/jobs/{id}/status` | Trạng thái + tiến độ job |
| `GET`  | `/api/jobs/{id}/segments` | Danh sách segments phụ đề |
| `GET`  | `/api/jobs/{id}/download/subtitle` | Tải file .srt/.vtt |
| `POST` | `/api/jobs/{id}/callback` | (Internal) Worker callback |
| `GET`  | `/health` | Health check |
| `WS`   | `/hubs/job` | SignalR WebSocket |

---

## 🔌 SignalR Client Example (JavaScript)

```javascript
import * as signalR from "@microsoft/signalr";

const connection = new signalR.HubConnectionBuilder()
  .withUrl("http://localhost:8080/hubs/job")
  .build();

// Lắng nghe events
connection.on("JobStatusChanged", (data) => console.log("Status:", data.status));
connection.on("JobCompleted", (data) => {
  console.log("Done! Video URL:", data.outputVideoUrl);
});
connection.on("JobFailed", (data) => console.error("Failed:", data.errorMessage));

await connection.start();

// Đăng ký theo dõi job
await connection.invoke("WatchJob", jobId);
```

---

## ⚙️ Cấu hình Whisper Model

| Model | VRAM | Tốc độ | Độ chính xác |
|-------|------|--------|--------------|
| `tiny` | ~1 GB | Rất nhanh | Thấp |
| `base` | ~1 GB | Nhanh | Tốt (mặc định) |
| `small` | ~2 GB | Vừa | Rất tốt |
| `medium` | ~5 GB | Chậm | Xuất sắc |
| `large-v3` | ~10 GB | Rất chậm | Tốt nhất |

Set trong `.env`: `WHISPER_MODEL=base`

---

## 🗄️ Database Schema

```
videos               ─── translation_jobs ─── job_steps
(metadata video)          (mỗi job dịch)       (log pipeline)
                              │
                          subtitle_segments
                          (text + timestamp)
```

---

## 📊 Tech Stack

| Layer | Technology |
|-------|-----------|
| API Gateway | C# ASP.NET Core 8, SignalR |
| Database | PostgreSQL 16 |
| Message Broker | RabbitMQ 3.13 |
| Object Storage | MinIO (S3-compatible) |
| AI/STT | OpenAI Whisper (offline) |
| Translation | Google Translate / DeepL / Gemini |
| Video Processing | FFmpeg |
| Workers | Python 3.11 |
| Container | Docker Compose |

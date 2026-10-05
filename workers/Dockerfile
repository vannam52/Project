FROM python:3.11-slim

# Cài FFmpeg (cần cho worker1 và worker4)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cài Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Thư mục tạm cho xử lý video
RUN mkdir -p /tmp/vs_processing

CMD ["python", "worker1_audio_extract.py"]

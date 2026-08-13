FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install yt-dlp via pip (lighter than maintaining a separate package)
RUN pip install --no-cache-dir yt-dlp

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir ".[api]"

COPY src/ src/
COPY .env.example .env.example

ENV THEIA_FRAMES_DIR=/data/frames
ENV THEIA_DATA_DIR=/data

VOLUME ["/data"]

CMD ["theia", "run", "--interval", "15"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# LibreOffice headless p/ DOC -> DOCX
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    libreoffice-writer \
    fonts-dejavu \
    fontconfig \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persistencia do Space
ENV HF_HOME=/data/.huggingface
ENV WORK_DIR=/data/work
ENV LOCAL_STORAGE_DIR=/data/storage

CMD ["python", "main.py"]

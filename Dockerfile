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

# Recommended for HF Docker Spaces (container runs with uid 1000)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH
WORKDIR $HOME/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

# Persistencia do Space
ENV HF_HOME=/tmp/.huggingface
ENV WORK_DIR=/tmp/work
ENV LOCAL_STORAGE_DIR=/tmp/storage

CMD ["python", "main.py"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && python -m spacy download en_core_web_sm

COPY . .

# Prefetch the embedding model (per config/clustering.toml) at build time
# so containers never hit the network for it at runtime. Importing the
# module itself loads/downloads the model.
RUN python -c "import workers.embeddings"

RUN mkdir -p /data

CMD ["python", "-m", "collector.runner"]
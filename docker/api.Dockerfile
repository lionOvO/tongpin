FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/srv/data HF_HOME=/opt/models
ARG DEBIAN_MIRROR=https://mirrors.cloud.tencent.com
RUN sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources && apt-get update && apt-get install -y --no-install-recommends antiword && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements-runtime-lock.txt requirements-vector.txt ./
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir -r requirements-runtime-lock.txt
ARG WITH_VECTORS=false
RUN if [ "$WITH_VECTORS" = "true" ]; then pip install --no-cache-dir -r requirements-vector.txt && python -c "from sentence_transformers import SentenceTransformer,CrossEncoder; SentenceTransformer('BAAI/bge-m3',device='cpu'); CrossEncoder('BAAI/bge-reranker-base',device='cpu')"; fi
RUN useradd --uid 10001 --create-home talent && mkdir -p /srv/data && chown talent:talent /srv/data
COPY app ./app
COPY config ./config
COPY scripts/manage_accounts.py ./scripts/manage_accounts.py
RUN chmod -R a+rX /srv/app /srv/config /srv/scripts
USER talent
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","1"]

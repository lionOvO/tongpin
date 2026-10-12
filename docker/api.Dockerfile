FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/srv/data HF_HOME=/opt/models
WORKDIR /srv
COPY requirements-lock.txt requirements-vector.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt
ARG WITH_VECTORS=false
RUN if [ "$WITH_VECTORS" = "true" ]; then pip install --no-cache-dir -r requirements-vector.txt && python -c "from sentence_transformers import SentenceTransformer,CrossEncoder; SentenceTransformer('BAAI/bge-m3',device='cpu'); CrossEncoder('BAAI/bge-reranker-base',device='cpu')"; fi
RUN useradd --uid 10001 --create-home talent && mkdir -p /srv/data && chown talent:talent /srv/data
COPY app ./app
COPY config ./config
USER talent
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]

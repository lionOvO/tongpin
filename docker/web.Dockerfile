FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt && useradd --uid 10001 --create-home talent
COPY web ./web
COPY .streamlit ./.streamlit
USER talent
EXPOSE 8501
CMD ["streamlit","run","web/Home.py","--server.address=0.0.0.0","--server.port=8501","--server.headless=true"]

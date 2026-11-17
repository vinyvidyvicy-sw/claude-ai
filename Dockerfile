FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/portal
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY config ./config
RUN useradd --system --uid 10001 portal && mkdir -p /srv/portal/data && chown portal /srv/portal/data
USER portal
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["python", "-m", "uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]

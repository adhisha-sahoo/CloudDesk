FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml /app/
COPY clouddesk /app/clouddesk
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home clouddesk && mkdir /data && chown clouddesk:clouddesk /data
COPY site /app/site
COPY runbooks /app/runbooks
COPY infra /app/infra
USER clouddesk
ENV CLOUDDESK_DATA_DIR=/data CLOUDDESK_EMBEDDED_MOTO=false
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "clouddesk.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
COPY requirements.lock ./
RUN pip install --no-cache-dir --timeout 60 --retries 1 -r requirements.lock
COPY customer-service-backend/ ./customer-service-backend/
CMD ["python", "customer-service-backend/scripts/test_all.py"]

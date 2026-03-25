FROM python:3.14-slim

WORKDIR /app

COPY cliproxyapi_cleanup_401.py .

ENTRYPOINT ["python", "cliproxyapi_cleanup_401.py"]

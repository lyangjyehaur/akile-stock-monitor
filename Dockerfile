FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir telethon requests

COPY monitor.py .
COPY config.json .

CMD ["python", "-u", "monitor.py"]

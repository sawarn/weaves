FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY weaves ./weaves

RUN groupadd --system --gid 10001 weaves \
    && useradd --system --uid 10001 --gid weaves --home-dir /app weaves \
    && chown -R weaves:weaves /app

USER 10001:10001
EXPOSE 8000

CMD ["uvicorn", "weaves.product.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

WORKDIR /app

COPY . /app

ENV HOST=0.0.0.0 \
    PORT=8080 \
    DATA_PATH=/data/contexts.json

EXPOSE 8080

VOLUME ["/data"]

CMD ["python", "-m", "infinite_context_mcp"]

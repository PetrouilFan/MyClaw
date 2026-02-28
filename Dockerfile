FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

RUN mkdir -p /app/workspace /app/logs

ENV PYTHONUNBUFFERED=1
ENV MYCLAW_WORKSPACE=/app/workspace

EXPOSE 8080

CMD ["python", "myclaw.py"]

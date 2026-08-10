FROM python:3.12-slim

WORKDIR /app

RUN apt-get update
RUN pip install --upgrade pip
RUN pip install uv

COPY pyproject.toml ./
COPY uv.lock ./
COPY README.md ./
RUN uv sync

COPY . .

CMD ["uv", "run", "fastapi", "run", "--root-path", "/job-aggregator/api"]
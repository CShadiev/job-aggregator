ARG PYTHON_DIGEST=sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

FROM python:3.12-slim@${PYTHON_DIGEST} AS builder

WORKDIR /app

# Install uv without pip's own cache bloating this layer
RUN pip install --no-cache-dir uv

# Copy only the dependency manifests first
COPY pyproject.toml uv.lock README.md ./

# Install deps only into .venv, using the lockfile exactly.
RUN uv sync --locked --no-install-project --no-dev

# Now bring in the source and install the project itself.
COPY . .
RUN uv sync --locked --no-dev

# ---------------------------------------------------------------------------
FROM python:3.12-slim@${PYTHON_DIGEST} AS runtime

# Non-root user: an RCE in the app should not hand out root-in-container for free.
RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app

# Pull in ONLY the built venv + app source from the builder stage —
# no compilers, no uv itself, no build-time cache left behind.
COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER app
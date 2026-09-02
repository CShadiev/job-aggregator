ARG PYTHON_DIGEST=sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

FROM python:3.13-slim@${PYTHON_DIGEST} AS builder

ENV UV_PYTHON_DOWNLOADS=0

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
FROM python:3.13-slim@${PYTHON_DIGEST} AS runtime

# Non-root user: an RCE in the app should not hand out root-in-container for free.
RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app

# Pull in ONLY the built venv + app source from the builder stage —
# no compilers, no uv itself, no build-time cache left behind.
COPY --from=builder /app /app

# The only writable locations, created deliberately.
RUN install -d -o app -g app -m 0750 /var/log/app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TEMP_DIR=/tmp \
    LOG_DIR=/var/log/app

USER app
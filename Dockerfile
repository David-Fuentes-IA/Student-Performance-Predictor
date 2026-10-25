# syntax=docker/dockerfile:1
#
# Student Performance Predictor - container image.
#
# Dockerfile = the recipe. `docker build` follows it and produces an IMAGE (the packaged, immutable
# application). `docker run` / `docker compose up` start CONTAINERS (running instances) of that image.
# Two stages keep the final image small: the first one only installs the dependencies.

# ---------- Stage 1: dependencies -------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# A virtual environment can be copied to the next stage as one folder, with nothing else from this stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Only requirements.txt is copied first: while it does not change, Docker reuses this (slow) layer.
COPY requirements.txt .
RUN pip install -r requirements.txt


# ---------- Stage 2: the runnable application ---------------------------------------------------
FROM python:3.12-slim AS runtime

# No .pyc files in the image; unbuffered output so `docker logs` shows lines immediately.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"

# Never run as root: if the application were compromised, the attacker would not own the container.
RUN groupadd --system app && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/logs /app/models && chown -R app:app /app
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .

# The model is not stored in git: it is trained here, at build time, so every image carries a model
# that matches its code (the application itself never trains at start-up).
# The sed strips Windows line endings from the entrypoint, which would otherwise break it on Linux.
RUN sed -i 's/\r$//' docker/entrypoint.sh && chmod +x docker/entrypoint.sh \
    && python scripts/train_model.py > /dev/null \
    && chown -R app:app /app/models
USER app

EXPOSE 8000

# Docker marks the container "unhealthy" when this fails (the slim image has no curl, hence Python).
# /health answers 200 whenever the application is up and reports the database and model state.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/app/docker/entrypoint.sh"]
# gunicorn serves the Flask app factory. 2 worker processes x 4 threads handle concurrent teachers;
# note that each worker keeps its own prediction cache.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "60", \
     "--access-logfile", "-", "webapp:create_app()"]

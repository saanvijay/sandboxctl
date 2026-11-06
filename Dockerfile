FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -U pip && pip install -r requirements.txt

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-deps -e .

RUN groupadd -g 10001 app && useradd -u 10001 -g app -s /sbin/nologin app
USER 10001:10001

EXPOSE 8080 9090
CMD ["uvicorn", "sandbox_ctl.boot:build_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]

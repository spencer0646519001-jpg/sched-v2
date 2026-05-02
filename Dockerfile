FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=app.deploy_settings

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY manage.py ./manage.py

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000", "--noreload"]

FROM python:3.12-slim@sha256:12316debbfb86890f6b2d825820612741ba527ad5a44e3902759141d572bfe8f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/python
WORKDIR /app
COPY deploy/live/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY python/screen_state.py /app/python/screen_state.py
COPY templates/screens/ /app/templates/screens/
COPY artifacts/live/session-conflict.png artifacts/live/connection-error.png /app/artifacts/live/
COPY web/live/ /app/web/live/
RUN chmod -R a+rX /app
USER 1000:1000
CMD ["python", "web/live/server.py"]

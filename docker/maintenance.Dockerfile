FROM docker:28-cli
RUN apk add --no-cache python3 py3-cryptography git
WORKDIR /opt/pengucoach-maintenance/program
COPY pengucoach/maintenance ./pengucoach/maintenance
RUN touch pengucoach/__init__.py
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DOCKER_HOST=unix:///var/run/docker.sock
ENTRYPOINT ["python3", "-m", "pengucoach.maintenance.agent", "--config", "/state/config.json"]

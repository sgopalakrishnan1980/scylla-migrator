FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI (static binary) - required for docker exec from within container
ARG DOCKER_VERSION=27.3.1
RUN curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_VERSION}.tgz | \
    tar xzvf - --strip-components=1 -C /usr/local/bin docker/docker

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py log4j2.properties log4j2-debug.properties ./
COPY templates/ templates/

RUN mkdir -p /app

EXPOSE 5000

ENV FLASK_APP=app.py
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=5000"]

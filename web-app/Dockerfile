FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ templates/

RUN mkdir -p /app

EXPOSE 5000

ENV FLASK_APP=app.py
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0", "--port=5000"]

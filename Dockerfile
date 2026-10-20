FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Deno JavaScript runtime
RUN curl -fsSL https://deno.land/install.sh | sh \
    && ln -s /root/.deno/bin/deno /usr/local/bin/deno

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY app.py .

EXPOSE 10000

CMD ["python", "app.py"]

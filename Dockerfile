FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Cuiaba DATABASE_URL=sqlite:////data/financas.db
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tzdata gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home-dir /app app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY start.sh /usr/local/bin/start.sh
RUN chmod 755 /usr/local/bin/start.sh && mkdir -p /data && chown app:app /data
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/start.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]

FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*
COPY . /app
RUN chmod +x /app/start-host.sh

ENV PORT=8080 \
    AA_BACKEND_PORT=8752 \
    AA_DATA_DIR=/tmp/approveaccept-data
EXPOSE 8080
CMD ["./start-host.sh"]

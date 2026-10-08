FROM node:24-bookworm-slim@sha256:51b1100cc2a83d370c6a60952e3f2989c8a43159d0e38586e090f3b3326efefd AS converter
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 make g++ pkg-config libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/converter
COPY converter/package.json converter/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts \
    && cd node_modules/canvas && npm run install \
    && npm cache clean --force

FROM python:3.13-slim-bookworm@sha256:f040863673aea2570c3ff6a5c3fb4c673a016cbc5375005ad145915922b6b78a
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libjpeg62-turbo libgif7 librsvg2-2 \
    fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY --from=converter /usr/local/bin/node /usr/local/bin/node
COPY --from=converter /opt/converter /opt/converter
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
ENV EMVIARY_CONVERTER=/opt/converter/node_modules/.bin/epaper-image-convert \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
EXPOSE 8080
CMD ["emviary", "serve"]

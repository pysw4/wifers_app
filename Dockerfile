# ---- Build Stage ----
FROM ubuntu:22.04 AS build

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies for Flutter
RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    xz-utils \
    zip \
    libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*

# Install Flutter SDK (pin to a specific stable version for reproducibility)
RUN git clone --depth 1 --branch stable https://github.com/flutter/flutter.git /flutter
ENV PATH="/flutter/bin:/flutter/bin/cache/dart-sdk/bin:${PATH}"

# Enable web support
RUN flutter config --enable-web

# Pre-create the gradle wrapper directory and create a fake completed download marker
# This prevents Flutter from trying to download the Gradle wrapper (which fails in Docker)
RUN mkdir -p /flutter/bin/cache/artifacts/gradle_wrapper && \
    mkdir -p /flutter/bin/cache/downloads/storage.googleapis.com/flutter_infra_release/gradle-wrapper && \
    touch /flutter/bin/cache/downloads/storage.googleapis.com/flutter_infra_release/gradle-wrapper/fd5c1f2c013565a3bea56ada6df9d2b8e96d56aa && \
    chmod -R 777 /flutter/bin/cache

# Set working directory
WORKDIR /app

# Copy the entire project (needed because pubspec.yaml references local assets)
COPY . .

# Run flutter pub get
RUN flutter pub get

# Build Flutter Web (release mode)
RUN flutter build web --release

# ---- Production Stage ----
FROM nginx:alpine

# Copy built web files to nginx
COPY --from=build /app/build/web /usr/share/nginx/html

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]

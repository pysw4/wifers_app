# ---- Build Stage ----
FROM debian:bookworm-slim AS build

# Install dependencies for Flutter
RUN apt-get update && apt-get install -y \
    curl \
    git \
    unzip \
    xz-utils \
    zip \
    libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*

# Install Flutter SDK
RUN git clone --depth 1 --branch stable https://github.com/flutter/flutter.git /flutter
ENV PATH="/flutter/bin:/flutter/bin/cache/dart-sdk/bin:${PATH}"

# Enable web support
RUN flutter config --enable-web

# Pre-create the gradle wrapper directory and create a dummy tar to prevent download
RUN mkdir -p /flutter/bin/cache/artifacts/gradle_wrapper && \
    mkdir -p /flutter/bin/cache/downloads/storage.googleapis.com && \
    touch /flutter/bin/cache/downloads/storage.googleapis.com/flutter_infra_release && \
    chmod -R 777 /flutter/bin/cache

# Set working directory
WORKDIR /app

# Copy project files
COPY pubspec.yaml pubspec.lock ./

# Use dart pub get instead of flutter pub get to avoid Android Gradle download
RUN dart pub get

# Copy the rest of the project
COPY . .

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

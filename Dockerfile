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

# Pre-create cache directories with proper permissions to avoid tar ownership issues
RUN mkdir -p /flutter/bin/cache/artifacts/gradle_wrapper && \
    mkdir -p /flutter/bin/cache/downloads && \
    chmod -R 777 /flutter/bin/cache

# Enable web support (skip Android/iOS artifacts)
RUN flutter config --enable-web --no-android --no-ios

# Set working directory
WORKDIR /app

# Copy project files
COPY pubspec.yaml pubspec.lock ./

# Disable analytics and skip Android-related downloads during pub get
RUN flutter pub get --no-precompile

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

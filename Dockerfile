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

# Pre-download the Gradle wrapper tar to avoid tar ownership issues
# The tar is extracted by flutter when running pub get, but the container's
# tar doesn't support --no-same-owner. We download and extract it manually first.
RUN mkdir -p /flutter/bin/cache/artifacts/gradle_wrapper && \
    curl -sL "https://storage.googleapis.com/flutter_infra_release/gradle-wrapper/fd5c1f2c013565a3bea56ada6df9d2b8e96d56aa/gradle-wrapper.tgz" \
    -o /tmp/gradle-wrapper.tgz && \
    tar -xzf /tmp/gradle-wrapper.tgz -C /flutter/bin/cache/artifacts/gradle_wrapper --no-same-owner 2>/dev/null || \
    tar -xzf /tmp/gradle-wrapper.tgz -C /flutter/bin/cache/artifacts/gradle_wrapper 2>/dev/null; \
    chmod -R 777 /flutter/bin/cache

# Set working directory
WORKDIR /app

# Copy project files
COPY pubspec.yaml pubspec.lock ./

# Now flutter pub get should work since gradle wrapper is already cached
RUN flutter pub get

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

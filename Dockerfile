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

# Install Flutter SDK
RUN git clone --depth 1 --branch stable https://github.com/flutter/flutter.git /flutter
ENV PATH="/flutter/bin:/flutter/bin/cache/dart-sdk/bin:${PATH}"

# Enable web support
RUN flutter config --enable-web

# Patch Flutter to skip Gradle wrapper download (we only need web)
# The Gradle wrapper download fails in Docker due to tar ownership issues.
# Since we're building for web only, we can safely disable this.
RUN sed -i 's/if (!foundVersion)/if (false)/' /flutter/packages/flutter_tools/lib/src/android/gradle_utils.dart && \
    sed -i 's/if (!foundVersion)/if (false)/' /flutter/packages/flutter_tools/lib/src/android/gradle.dart 2>/dev/null; \
    true

# Set working directory
WORKDIR /app

# Copy project files
COPY pubspec.yaml pubspec.lock ./

# Run flutter pub get (should now skip Gradle download)
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

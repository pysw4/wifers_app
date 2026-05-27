#!/bin/bash
# Deploy Flutter Web to Render Static Site via gh-pages branch
set -e

echo "🔨 Building Flutter Web..."
flutter build web --release

echo "📂 Copying heatmap static files..."
cp -r web/heatmaps build/web/heatmaps
echo "   ✅ Heatmap files copied to build/web/heatmaps/"

echo "📦 Deploying to gh-pages branch..."
cd build/web

# Initialize a new git repo for the build output
git init
git checkout -b gh-pages
git add .
git commit -m "Deploy Flutter Web - $(date '+%Y-%m-%d %H:%M')"

# Push to gh-pages branch (force)
git remote add origin git@github.com:pysw4/wifers_app.git
git push origin gh-pages --force

echo "✅ Deploy complete!"
echo "🌐 Visit: https://pysw4.github.io/wifers_app"

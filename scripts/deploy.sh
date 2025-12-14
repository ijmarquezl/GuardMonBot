#!/bin/bash
set -e

# Configuration
APP_DIR="/opt/guardmonbot"
SERVICE_NAME="guardmonbot"

echo "🚀 Starting Deployment..."

if [ ! -d "$APP_DIR" ]; then
    echo "❌ Error: Directory $APP_DIR does not exist."
    exit 1
fi

cd $APP_DIR

echo "📥 Pulling latest changes..."
git pull origin main

echo "📦 Installing dependencies..."
# Check if .venv exists, if not warn (or create, but user should have set it up)
if [ -f ".venv/bin/pip" ]; then
    .venv/bin/pip install -r guardian_monitor/requirements.txt
else
    echo "⚠️ Warning: Virtual environment not found at .venv. Skipping pip install."
fi

echo "🔄 Restarting Service..."
systemctl restart $SERVICE_NAME

echo "✅ Deployment Complete!"

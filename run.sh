#!/usr/bin/env bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Change to script directory
cd "$(dirname "$0")"

# Track if we started Qdrant (to know if we should stop it)
QDRANT_STARTED=false
PYTHON_PID=""

cleanup() {
    echo -e "\n${YELLOW}Shutting down...${NC}"

    # Stop Python process if running
    if [ -n "$PYTHON_PID" ] && kill -0 "$PYTHON_PID" 2>/dev/null; then
        echo -e "${YELLOW}Stopping Python server...${NC}"
        kill -TERM "$PYTHON_PID" 2>/dev/null || true
        wait "$PYTHON_PID" 2>/dev/null || true
    fi

    # Stop Qdrant container
    if [ "$QDRANT_STARTED" = true ]; then
        echo -e "${YELLOW}Stopping Qdrant...${NC}"
        docker compose stop qdrant
    fi

    echo -e "${GREEN}Shutdown complete.${NC}"
    exit 0
}

# Trap signals
trap cleanup SIGINT SIGTERM

echo -e "${GREEN}Starting Chatty...${NC}"

# Start Qdrant
echo -e "${YELLOW}Starting Qdrant database...${NC}"
docker compose up -d qdrant
QDRANT_STARTED=true

# Wait for Qdrant to be healthy
echo -e "${YELLOW}Waiting for Qdrant to be ready...${NC}"
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    # Check if Qdrant REST API is actually responding (not just port open)
    # Use 127.0.0.1 explicitly since Docker may not bind to IPv6
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:6333/collections 2>/dev/null || echo "000")
    if [ "$RESPONSE" = "200" ]; then
        echo -e "${GREEN}Qdrant is ready!${NC}"
        break
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        echo -e "${RED}Qdrant failed to start after $MAX_RETRIES attempts${NC}"
        cleanup
        exit 1
    fi

    echo -e "  Waiting for Qdrant... (attempt $RETRY_COUNT/$MAX_RETRIES)"
    sleep 1
done

# Start Python server
echo -e "${GREEN}Starting Python server...${NC}"
uv run --env-file .env -m src.main &
PYTHON_PID=$!

# Wait for Python process to exit
wait "$PYTHON_PID"

#!/usr/bin/env bash
set -euo pipefail

# ── Taokaka startup script ──
# Ensures all required services are up before launching main.py

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Docker Desktop on macOS doesn't always add itself to PATH
if ! command -v docker &>/dev/null; then
    for d in /Applications/Docker.app/Contents/Resources/bin /usr/local/bin /opt/homebrew/bin; do
        if [ -x "$d/docker" ]; then
            export PATH="$d:$PATH"
            break
        fi
    done
fi

ES_URL="http://localhost:9200"
ES_CONTAINER="taokaka-es"
ES_IMAGE="elasticsearch:8.17.0"
LLM_URL="http://127.0.0.1:1234"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[taokaka]${NC} $1"; }
ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $1"; }
fail() { echo -e "${RED}  ✗${NC} $1"; }

# ── Wait for a service to respond ──
wait_for() {
    local name="$1" url="$2" max_wait="${3:-30}"
    local elapsed=0
    while ! curl -sf "$url" >/dev/null 2>&1; do
        if [ "$elapsed" -ge "$max_wait" ]; then
            fail "$name did not respond at $url after ${max_wait}s"
            return 1
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    ok "$name is up ($url)"
    return 0
}

# ── 1. Python venv ──
log "Checking Python environment..."
if [ -d "venv" ]; then
    source venv/bin/activate 2>/dev/null && ok "Activated venv" || warn "venv exists but could not activate"
elif [ -n "${VIRTUAL_ENV:-}" ]; then
    ok "Already in virtualenv: $VIRTUAL_ENV"
else
    warn "No venv found and no virtualenv active — using system Python"
fi

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" &>/dev/null; then
    fail "Python not found. Set PYTHON env var or activate your venv."
    exit 1
fi
ok "Python: $($PYTHON --version 2>&1)"

# ── 2. Elasticsearch ──
log "Checking Elasticsearch..."
if curl -sf "$ES_URL" >/dev/null 2>&1; then
    ok "Elasticsearch already running"
else
    if ! command -v docker &>/dev/null; then
        fail "Docker not found and Elasticsearch is not running at $ES_URL"
        fail "Install Docker or start Elasticsearch manually, then re-run."
        exit 1
    fi

    # Ensure Docker daemon is running (macOS: launch Docker Desktop if needed)
    if ! docker info >/dev/null 2>&1; then
        if [ -d "/Applications/Docker.app" ]; then
            log "Starting Docker Desktop..."
            open -a Docker
            local waited=0
            while ! docker info >/dev/null 2>&1; do
                if [ "$waited" -ge 30 ]; then
                    fail "Docker Desktop did not start after 30s"
                    exit 1
                fi
                sleep 2
                waited=$((waited + 2))
            done
            ok "Docker Desktop started"
        else
            fail "Docker daemon is not running. Start Docker and re-run."
            exit 1
        fi
    fi

    # Check if container exists but is stopped
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${ES_CONTAINER}$"; then
        log "Starting existing Elasticsearch container..."
        docker start "$ES_CONTAINER" 2>&1 | sed 's/^/    /'
    else
        log "Creating Elasticsearch container..."
        docker run -d \
            --name "$ES_CONTAINER" \
            -p 9200:9200 \
            -e "discovery.type=single-node" \
            -e "xpack.security.enabled=false" \
            -e "ES_JAVA_OPTS=-Xms512m -Xmx512m" \
            "$ES_IMAGE" 2>&1 | sed 's/^/    /'
    fi

    log "Waiting for Elasticsearch to be ready..."
    if ! wait_for "Elasticsearch" "$ES_URL" 60; then
        fail "Could not start Elasticsearch. Check: docker logs $ES_CONTAINER"
        exit 1
    fi
fi

# ── 3. LLM endpoint ──
log "Checking LLM endpoint..."
if curl -sf "$LLM_URL/v1/models" >/dev/null 2>&1; then
    ok "LLM endpoint responding"
else
    warn "LLM endpoint not responding at $LLM_URL"
    warn "Start your LLM server (e.g. LM Studio) and it will be picked up when needed."
    warn "Continuing anyway — Tao won't be able to respond until it's up."
fi

# ── 4. Node.js / Frontend deps ──
log "Checking frontend..."
if [ -d "$FRONTEND_DIR" ]; then
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        log "Installing frontend dependencies..."
        (cd "$FRONTEND_DIR" && npm install 2>&1 | tail -3 | sed 's/^/    /')
    fi
    ok "Frontend ready (auto-started by main.py)"
else
    warn "Frontend directory not found at $FRONTEND_DIR — skipping"
fi

# ── 5. Migration check ──
if [ -d "memories/chroma.db" ]; then
    # Check if ES index has data
    ES_COUNT=$(curl -sf "$ES_URL/neuro_memories/_count" 2>/dev/null | $PYTHON -c "import sys,json; print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo "0")
    if [ "$ES_COUNT" = "0" ]; then
        warn "ChromaDB data found but Elasticsearch index is empty."
        echo -e "    Run: ${CYAN}$PYTHON scripts/migrate_chroma_to_es.py${NC} to migrate your memories."
    fi
fi

# ── 6. Launch ──
echo ""
log "Starting Taokaka..."
echo ""
exec $PYTHON main.py "$@"

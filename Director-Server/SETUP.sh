#!/usr/bin/env bash
# =============================================================================
# Director-Server Island Setup — Kali Linux
# =============================================================================
# Purges broken monorepo artifacts, installs dependencies in isolation,
# and starts all services on their correct ports.
# =============================================================================
set -euo pipefail

PROJECT_DIR="$HOME/Director-Server"
MONOREPO_DIR="$HOME/director-project"   # The broken monorepo

echo "=============================================="
echo " Director-Server Island Setup"
echo "=============================================="

# ---------------------------------------------------------------------------
# STEP 1: Purge corrupted monorepo artifacts
# ---------------------------------------------------------------------------
echo ""
echo "[1/6] Purging broken monorepo symlinks and missing directories..."

if [ -d "$MONOREPO_DIR" ]; then
    # Remove the dangling packages/agents symlink that breaks everything.
    if [ -L "$MONOREPO_DIR/packages/agents" ] || [ -d "$MONOREPO_DIR/packages/agents" ]; then
        echo "  Removing broken packages/agents ..."
        rm -rf "$MONOREPO_DIR/packages/agents"
    fi

    # Kill any stale node_modules symlinks pointing into the void.
    find "$MONOREPO_DIR" -maxdepth 4 -name "node_modules" -type l -exec rm -f {} \; 2>/dev/null || true

    echo "  Monorepo artifacts purged."
else
    echo "  Monorepo not found — nothing to purge."
fi

# ---------------------------------------------------------------------------
# STEP 2: Ensure the island project directory exists
# ---------------------------------------------------------------------------
echo ""
echo "[2/6] Setting up $PROJECT_DIR ..."
mkdir -p "$PROJECT_DIR/outputs"
mkdir -p "$PROJECT_DIR/pages/api"
mkdir -p "$PROJECT_DIR/pages/agent"
mkdir -p "$PROJECT_DIR/lib"

# Copy all island files into place if they aren't already there.
# (In production you'd clone from git; this is the local-deploy path.)
if [ -f "$PROJECT_DIR/package.json" ]; then
    echo "  Project files already present."
else
    echo "  [!] Project files not found — deploy them to $PROJECT_DIR first."
    echo "  Expected: package.json, next.config.js, .env.local, listen_blender.py, etc."
fi

# ---------------------------------------------------------------------------
# STEP 3: Install Node dependencies (--no-workspaces isolates from monorepo)
# ---------------------------------------------------------------------------
echo ""
echo "[3/6] Installing Node dependencies (--no-workspaces) ..."
cd "$PROJECT_DIR"

# Purge any leftover node_modules from a broken install.
rm -rf node_modules package-lock.json

# Install with --no-workspaces so npm never tries to resolve the monorepo root.
npm install --no-workspaces --legacy-peer-deps

echo "  Dependencies installed."

# ---------------------------------------------------------------------------
# STEP 4: Verify Docker PostgreSQL container
# ---------------------------------------------------------------------------
echo ""
echo "[4/6] Verifying PostgreSQL Docker container..."

if docker ps --format '{{.Names}}' | grep -q 'director_ledger'; then
    echo "  Container 'director_ledger' is running."
else
    echo "  [!] Container not running. Attempting to start..."
    if docker ps -a --format '{{.Names}}' | grep -q 'director_ledger'; then
        docker start director_ledger
        echo "  Container started."
    else
        echo "  [!] Container does not exist. Creating it..."
        docker run -d \
            --name director_ledger \
            -e POSTGRES_USER=bjornjasper \
            -e POSTGRES_PASSWORD=1278458kaliko787 \
            -e POSTGRES_DB=director_ledger \
            -p 5433:5432 \
            postgres:16
        echo "  Container created and running."
    fi
fi

# ---------------------------------------------------------------------------
# STEP 5: Run the database verification script
# ---------------------------------------------------------------------------
echo ""
echo "[5/6] Running database verification..."
sleep 2  # Give Postgres a moment if it just started.
node "$PROJECT_DIR/test_ledger.js"

# ---------------------------------------------------------------------------
# STEP 6: Start the frontend on port 8081
# ---------------------------------------------------------------------------
echo ""
echo "[6/6] Starting Next.js on port 8081..."
echo "  Dashboard:  http://127.0.0.1:8081"
echo "  ZeroClaw:   http://127.0.0.1:8081/agent"
echo ""
cd "$PROJECT_DIR"
npm run dev

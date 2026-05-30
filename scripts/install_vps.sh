#!/usr/bin/env bash
# VPS bootstrap for QuantBot (Ubuntu/Debian). Installs Docker + Compose, clones
# the repo, prepares .env and starts the stack. Run as a sudo-capable user.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/bryan-helsens/Bot.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/quantbot}"

echo "==> Updating system packages"
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl git ufw

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Installing Docker"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi

echo "==> Cloning repository into ${INSTALL_DIR}"
if [ ! -d "${INSTALL_DIR}/.git" ]; then
  git clone "${REPO_URL}" "${INSTALL_DIR}"
fi
cd "${INSTALL_DIR}"

if [ ! -f .env ]; then
  echo "==> Creating .env from template — EDIT IT before going live"
  cp .env.example .env
  # Generate secrets.
  ENC_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null || true)"
  JWT="$(openssl rand -hex 32)"
  [ -n "${ENC_KEY}" ] && sed -i "s|^SECURITY__ENCRYPTION_KEY=.*|SECURITY__ENCRYPTION_KEY=${ENC_KEY}|" .env || true
  sed -i "s|^API__JWT_SECRET=.*|API__JWT_SECRET=${JWT}|" .env
fi

echo "==> Configuring firewall (SSH + dashboard + API)"
sudo ufw allow OpenSSH || true
sudo ufw allow 5173/tcp || true
sudo ufw allow 8000/tcp || true
sudo ufw --force enable || true

echo "==> Building and starting the stack"
sudo docker compose up -d --build

cat <<'EOF'

============================================================
 QuantBot is starting.
   - Dashboard:  http://<server-ip>:5173
   - API docs:   http://<server-ip>:8000/docs
 IMPORTANT:
   1. Edit .env: set BINANCE__TESTNET=true first, add API keys.
   2. Start in paper mode (TRADING_MODE=paper) and validate.
   3. Only switch to live after thorough testing.
   View logs:  docker compose logs -f
============================================================
EOF

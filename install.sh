#!/usr/bin/env bash
# =============================================================================
# Dr. Aria — Personal Psychologist Agent
# Ubuntu 24.04 VM Setup Script
#
# Usage:
#   curl -fsSL <raw_url>/install.sh | bash
#   OR: bash install.sh
#
# What this does:
#   1. System updates and base dependencies
#   2. Installs uv (Python package manager)
#   3. Installs hermes-agent (Dr. Aria fork)
#   4. Configures ~/.hermes with the psychologist soul and skills
#   5. Installs Tailscale for secure private networking
#   6. Sets up SSH key for remote access
#   7. Creates a systemd service for the hermes gateway
# =============================================================================

set -euo pipefail

# ─── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[dr-aria]${NC} $*"; }
success() { echo -e "${GREEN}[✓]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# ─── Config — edit these before running ───────────────────────────────────────
AGENT_USER="${AGENT_USER:-draria}"
REPO_URL="${REPO_URL:-https://github.com/groxaxo/hermes-psychologist}"
HERMES_HOME="/home/${AGENT_USER}/.hermes"

# SSH public key — set DR_ARIA_SSH_PUBKEY env var or paste it here
SSH_PUBKEY="${DR_ARIA_SSH_PUBKEY:-}"

# Tailscale auth key — set DR_ARIA_TAILSCALE_KEY env var
TAILSCALE_AUTHKEY="${DR_ARIA_TAILSCALE_KEY:-}"

# OpenAI / model API key — set DR_ARIA_API_KEY env var
OPENAI_API_KEY="${DR_ARIA_API_KEY:-}"

# ─── Pre-flight checks ────────────────────────────────────────────────────────
[[ "$(id -u)" -eq 0 ]] || error "Run as root: sudo bash install.sh"

info "Ubuntu version: $(lsb_release -rs 2>/dev/null || cat /etc/os-release | grep VERSION_ID)"

# ─── 1. System updates ────────────────────────────────────────────────────────
info "Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl git build-essential ca-certificates \
    gnupg lsb-release software-properties-common \
    openssh-server ufw fail2ban \
    python3 python3-pip python3-venv \
    python3-dev gcc \
    htop tmux jq ripgrep
success "System packages installed"

# ─── 2. Create agent user ─────────────────────────────────────────────────────
if ! id -u "${AGENT_USER}" &>/dev/null; then
    info "Creating user: ${AGENT_USER}"
    useradd -m -s /bin/bash -G sudo "${AGENT_USER}"
    echo "${AGENT_USER} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${AGENT_USER}"
    chmod 440 "/etc/sudoers.d/${AGENT_USER}"
    success "User ${AGENT_USER} created"
else
    info "User ${AGENT_USER} already exists"
fi

# ─── 3. SSH hardening + key setup ─────────────────────────────────────────────
info "Configuring SSH..."
SSH_DIR="/home/${AGENT_USER}/.ssh"
mkdir -p "${SSH_DIR}"
chmod 700 "${SSH_DIR}"

if [[ -n "${SSH_PUBKEY}" ]]; then
    echo "${SSH_PUBKEY}" >> "${SSH_DIR}/authorized_keys"
    chmod 600 "${SSH_DIR}/authorized_keys"
    chown -R "${AGENT_USER}:${AGENT_USER}" "${SSH_DIR}"
    success "SSH public key installed for ${AGENT_USER}"
else
    warn "No SSH_PUBKEY set. Set DR_ARIA_SSH_PUBKEY env var before running."
    warn "You can add it later: sudo -u ${AGENT_USER} bash -c 'echo YOUR_KEY >> ~/.ssh/authorized_keys'"
fi

# Harden SSH daemon
cat > /etc/ssh/sshd_config.d/90-draria.conf << 'EOF'
PasswordAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
EOF

systemctl restart ssh
success "SSH hardened (password auth disabled, root login disabled)"

# ─── 4. Firewall ──────────────────────────────────────────────────────────────
info "Configuring UFW firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 41641/udp   # Tailscale
ufw allow 8765/tcp    # Voice Gateway (restrict to tailscale later)
ufw --force enable
success "Firewall configured"

# ─── 5. Fail2ban ──────────────────────────────────────────────────────────────
systemctl enable fail2ban --quiet
systemctl start fail2ban
success "fail2ban enabled"

# ─── 6. Install uv ────────────────────────────────────────────────────────────
info "Installing uv (Python package manager)..."
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Add to PATH for this script
    export PATH="${HOME}/.cargo/bin:${HOME}/.local/bin:${PATH}"
fi
# Install for the agent user too
sudo -u "${AGENT_USER}" bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' 2>/dev/null || true
success "uv installed"

# ─── 7. Clone the repo ────────────────────────────────────────────────────────
INSTALL_DIR="/opt/hermes-psychologist"
info "Cloning Dr. Aria agent to ${INSTALL_DIR}..."
if [[ -d "${INSTALL_DIR}" ]]; then
    warn "Directory exists — pulling latest changes"
    git -C "${INSTALL_DIR}" pull --quiet
else
    git clone --depth 1 "${REPO_URL}" "${INSTALL_DIR}" 2>&1 | tail -3
fi
chown -R "${AGENT_USER}:${AGENT_USER}" "${INSTALL_DIR}"
success "Repository cloned"

# ─── 8. Install hermes-agent with uv ──────────────────────────────────────────
info "Installing hermes-agent Python package..."
sudo -u "${AGENT_USER}" bash -c "
    cd ${INSTALL_DIR}
    export PATH=\"\$HOME/.cargo/bin:\$HOME/.local/bin:\$PATH\"
    uv venv --python 3.11 .venv 2>&1 | tail -2
    uv pip install -e '.[all]' --quiet 2>&1 | tail -5 || \
    uv pip install -e '.' --quiet 2>&1 | tail -5
"
success "hermes-agent installed"

# ─── 9. Configure ~/.hermes ───────────────────────────────────────────────────
info "Configuring ~/.hermes for Dr. Aria..."
sudo -u "${AGENT_USER}" mkdir -p "${HERMES_HOME}/skills"

# Copy the psychologist soul
sudo -u "${AGENT_USER}" cp "${INSTALL_DIR}/docker/SOUL.md" "${HERMES_HOME}/SOUL.md"

# Copy the mental-health skills
sudo -u "${AGENT_USER}" cp -r "${INSTALL_DIR}/skills/mental-health" "${HERMES_HOME}/skills/"

# Write the config
sudo -u "${AGENT_USER}" bash -c "cat > ${HERMES_HOME}/config.yaml << 'YAML'
# Dr. Aria — Personal Psychologist Agent Configuration
agent:
  persona_file: \"~/.hermes/SOUL.md\"
  max_iterations: 60
  save_trajectories: false

model: \"gpt-4o\"

memory:
  enabled: true
  provider: \"local\"

display:
  theme: \"calm\"

skills:
  paths:
    - \"~/.hermes/skills\"
  auto_load:
    - \"mental-health/emotional-support\"
    - \"mental-health/cognitive-behavioral\"
    - \"mental-health/gottman-method\"
    - \"mental-health/ifs-parts-work\"
    - \"mental-health/act-therapy\"
    - \"mental-health/somatic-grounding\"
    - \"mental-health/session-tracking\"
    - \"mental-health/crisis-support\"

gateway:
  platform: \"telegram\"
  auto_start: false

logging:
  level: \"INFO\"
YAML"

success "~/.hermes configured"

# ─── 10. Write .env ───────────────────────────────────────────────────────────
if [[ -n "${OPENAI_API_KEY}" ]]; then
    sudo -u "${AGENT_USER}" bash -c "cat > ${HERMES_HOME}/.env << EOF
OPENAI_API_KEY=${OPENAI_API_KEY}
EOF
chmod 600 ${HERMES_HOME}/.env"
    success ".env written with API key"
else
    warn "No DR_ARIA_API_KEY set. Add OPENAI_API_KEY to ${HERMES_HOME}/.env manually."
    sudo -u "${AGENT_USER}" bash -c "cat > ${HERMES_HOME}/.env << 'EOF'
# Add your API key here
OPENAI_API_KEY=sk-YOUR_KEY_HERE
EOF
chmod 600 ${HERMES_HOME}/.env"
fi

# ─── 11. Create PATH wrapper ──────────────────────────────────────────────────
cat > /usr/local/bin/dr-aria << EOF
#!/bin/bash
export PATH="/opt/hermes-psychologist/.venv/bin:\$HOME/.cargo/bin:\$HOME/.local/bin:\$PATH"
cd /opt/hermes-psychologist
exec .venv/bin/hermes "\$@"
EOF
chmod +x /usr/local/bin/dr-aria
success "dr-aria command available at /usr/local/bin/dr-aria"

# ─── 12a. Install voice gateway ───────────────────────────────────────────────
VOICE_GW_DIR="${INSTALL_DIR}/voice-gateway"
if [[ -d "${VOICE_GW_DIR}" ]]; then
    info "Installing voice gateway Python dependencies..."
    sudo -u "${AGENT_USER}" bash -c "
        export PATH=\"\$HOME/.cargo/bin:\$HOME/.local/bin:\$PATH\"
        cd ${VOICE_GW_DIR}
        uv venv --python 3.11 .venv 2>&1 | tail -2
        uv pip install -r requirements.txt --quiet 2>&1 | tail -5
    "
    success "Voice gateway installed"

    # Write voice gateway .env
    sudo -u "${AGENT_USER}" bash -c "cat > ${VOICE_GW_DIR}/.env << 'VGEOF'
# Auto-generated by install.sh — edit to add your Telnyx credentials
XAI_API_KEY=\${XAI_API_KEY:-}
XAI_BASE_URL=https://api.x.ai/v1
LLM_MODEL=grok-3-mini
TTS_VOICE=luna
TTS_CODEC=alaw
TTS_SAMPLE_RATE=8000
TTS_MODEL=grok-voice-fast-1.0
TELNYX_API_KEY=
TELNYX_PHONE_NUMBER=
TELNYX_MEDIA_WS_URL=
VOICE_GATEWAY_PORT=8765
VAD_SILENCE_MS=700
LOG_LEVEL=info
VGEOF
chmod 600 ${VOICE_GW_DIR}/.env"

    # Patch the API key from hermes .env if present
    XAI_KEY_IN_ENV="\$(grep -oP 'XAI_API_KEY=\K.*' ${HERMES_HOME}/.env 2>/dev/null || true)"
    if [[ -n "\${XAI_KEY_IN_ENV}" ]]; then
        sed -i "s|XAI_API_KEY=.*|XAI_API_KEY=\${XAI_KEY_IN_ENV}|" "${VOICE_GW_DIR}/.env"
    fi

    # Systemd service for voice gateway
    cat > /etc/systemd/system/dr-aria-voice.service << SVCEOF
[Unit]
Description=Dr. Aria Voice Gateway (Telnyx WebSocket)
After=network.target dr-aria.service

[Service]
Type=simple
User=${AGENT_USER}
WorkingDirectory=${VOICE_GW_DIR}
EnvironmentFile=${VOICE_GW_DIR}/.env
Environment="PATH=${VOICE_GW_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=${VOICE_GW_DIR}/.venv/bin/python server.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=dr-aria-voice

[Install]
WantedBy=multi-user.target
SVCEOF

    systemctl daemon-reload
    success "Voice gateway systemd service created (dr-aria-voice.service)"
else
    warn "voice-gateway/ directory not found in repo — skipping voice gateway setup"
fi

# ─── 12. Systemd service ─────────────────────────────────────────────────────
info "Creating systemd service..."
cat > /etc/systemd/system/dr-aria.service << EOF
[Unit]
Description=Dr. Aria Personal Psychologist Agent
After=network.target

[Service]
Type=simple
User=${AGENT_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${HERMES_HOME}/.env
Environment="PATH=${INSTALL_DIR}/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=${INSTALL_DIR}/.venv/bin/hermes --no-banner
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=dr-aria

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
success "Systemd service created (dr-aria.service)"

# ─── 13. Tailscale ────────────────────────────────────────────────────────────
info "Installing Tailscale..."
if ! command -v tailscale &>/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
    success "Tailscale installed"
else
    info "Tailscale already installed"
fi

systemctl enable tailscaled --quiet
systemctl start tailscaled

if [[ -n "${TAILSCALE_AUTHKEY}" ]]; then
    info "Connecting to Tailscale network..."
    tailscale up --authkey="${TAILSCALE_AUTHKEY}" --hostname="dr-aria-$(hostname -s)" --accept-routes
    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "pending")
    success "Tailscale connected — IP: ${TAILSCALE_IP}"
else
    warn "No TAILSCALE_AUTHKEY set. Run manually after install:"
    warn "  sudo tailscale up --authkey=<YOUR_KEY> --hostname=dr-aria"
fi

# Allow Tailscale traffic through firewall
ufw allow in on tailscale0
success "Tailscale firewall rule added"

# ─── 14. Summary ──────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}   Dr. Aria — Personal Psychologist Agent — Setup Complete    ${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  Agent user:    ${BLUE}${AGENT_USER}${NC}"
echo -e "  Install dir:   ${BLUE}${INSTALL_DIR}${NC}"
echo -e "  Config:        ${BLUE}${HERMES_HOME}/config.yaml${NC}"
echo -e "  Soul:          ${BLUE}${HERMES_HOME}/SOUL.md${NC}"
echo -e "  API keys:      ${BLUE}${HERMES_HOME}/.env${NC}"
echo ""
echo -e "  ${YELLOW}Next steps:${NC}"
echo -e "  1. Add your API keys:         nano ${HERMES_HOME}/.env"
echo -e "     (also edit voice-gateway .env with Telnyx credentials)"
[[ -z "${TAILSCALE_AUTHKEY}" ]] && echo -e "  2. Join Tailscale:            sudo tailscale up --authkey=YOUR_KEY"
[[ -z "${SSH_PUBKEY}" ]]        && echo -e "  3. Add SSH key:               echo 'YOUR_PUBKEY' >> /home/${AGENT_USER}/.ssh/authorized_keys"
echo -e "  4. Start the agent:           sudo systemctl enable --now dr-aria"
echo -e "  5. Start voice gateway:       sudo systemctl enable --now dr-aria-voice"
echo -e "     (add Telnyx credentials first:  nano ${INSTALL_DIR}/voice-gateway/.env)"
echo ""
echo -e "  ${BLUE}SSH access:${NC}  ssh ${AGENT_USER}@$(hostname -I | awk '{print $1}')"
[[ -n "${TAILSCALE_AUTHKEY}" ]] && echo -e "  ${BLUE}Tailscale:${NC}   ssh ${AGENT_USER}@dr-aria"
echo ""

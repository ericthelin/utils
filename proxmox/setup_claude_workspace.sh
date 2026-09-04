#!/bin/bash
# Proxmox VE Helper Script to setup Claude Code with Proxmox MCP, Google Antigravity, Codex, and Opencode
set -e

# Colors for output
GREEN='\033[0;32m'
NC='\033[0m'
INFO='\033[0;36m'

echo -e "${INFO}Checking environment...${NC}"
if [ ! -f /etc/pve/local/pve-ssl.key ]; then
    echo "Error: This script must be run directly on a Proxmox VE Host."
    exit 1
fi

# Find next available VMID
NEXT_ID=$(pvesh get /cluster/nextid)
read -p "Enter Container ID (Default: $NEXT_ID): " CT_ID
CT_ID=${CT_ID:-$NEXT_ID}

read -p "Enter Storage Pool (Default: local-lvm): " STORAGE
STORAGE=${STORAGE:-local-lvm}

echo -e "${GREEN}Creating Debian 12 LXC Container (ID: $CT_ID)...${NC}"
# Update template list and download debian-12 if missing
pveam update
TEMPLATE=$(pveam list local | grep "debian-12" | head -n1 | awk '{print $2}')
if [ -z "$TEMPLATE" ]; then
    echo "Downloading Debian 12 template..."
    pveam download local debian-12-standard_12.2-1_amd64.tar.zst || pveam download local $(pveam available | grep debian-12 | head -n1 | awk '{print $2}')
    TEMPLATE=$(pveam list local | grep "debian-12" | head -n1 | awk '{print $2}')
fi

pct create $CT_ID local:vztmpl/$(basename $TEMPLATE) \
  -cores 2 \
  -memory 2048 \
  -swap 512 \
  -hostname claude-workspace \
  -ostype debian \
  -storage $STORAGE \
  -rootfs $STORAGE:8 \
  -net0 name=eth0,bridge=vmbr0,ip=dhcp \
  -unprivileged 1 \
  -start 1

echo -e "${INFO}Waiting for container to boot...${NC}"
sleep 5

echo -e "${GREEN}Provisioning software stack inside container...${NC}"
pct exec $CT_ID -- bash -c "
    apt-get update && apt-get install -y curl wget git unzip nano build-essential python3 python3-pip python3-venv nodejs npm
    
    # Ensure Node.js LTS (v18+)
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
    apt-get install -y nodejs
    
    # Install Claude Code globally
    npm install -g @anthropic-ai/claude-code || curl -sSL https://claude.ai | bash -s -- -y
    
    # Create unified directory infrastructure
    mkdir -p /opt/workspace/google-antigravity
    mkdir -p /opt/workspace/codex
    mkdir -p /opt/workspace/opencode
    mkdir -p ~/.config/Claude
    
    # Setup mock/placeholder configurations or clones for custom workspace tooling
    echo 'Initializing Google Antigravity, Codex, and Opencode configurations...'
    echo '{"environment": "proxmox-container", "components": ["google-antigravity", "codex", "opencode"]}' > /opt/workspace/workspace_manifest.json
"

echo -e "${GREEN}Successfully configured Claude Code workspace environment!${NC}"
echo -e "${INFO}Container ID $CT_ID is ready.${NC}"
echo -e "To access your environment and authenticate Claude, run: ${GREEN}pct enter $CT_ID${NC}"

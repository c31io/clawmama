# ClawMama

Telegram bot for managing Firecracker microVMs with OpenClaw.

> **Warning: Early Stage** - This project is under active development. APIs and features may change.

## Contributing

Contributions welcome! Please open an issue or PR on GitHub.

## Features

- Create and manage Ubuntu microVMs using Firecracker
- Install and setup OpenClaw in VMs
- Pause/resume, stop/start VM lifecycle management
- Backup and recover VM snapshots
- Network isolation to prevent VMs from attacking the host

## Requirements

- Linux with KVM support (or WSL2 on Windows)
- Python 3.10+
- Firecracker binary
- Telegram bot token

## Installation

```bash
# Clone and setup
git clone https://github.com/yourusername/clawmama.git
cd clawmama
uv sync

# Configure - copy template and edit
cp template.config.yaml ~/.config/clawmama/config.yaml
# Or use ./config.yaml for local development
```

## Usage

```bash
uv run python main.py
```

### Bot Commands

| Command | Description |
| --------- | ------------- |
| `/start` | Welcome message |
| `/help` | Show available commands |
| `/list` | List all VMs |
| `/create` | Create a new VM (interactive) |
| `/status <name>` | Check VM status |
| `/run <name>` | Start a VM |
| `/stop <name>` | Stop a VM |
| `/pause <name>` | Pause a VM |
| `/resume <name>` | Resume a VM |
| `/backup <name>` | Create backup |
| `/recover <name>` | Recover from backup |
| `/delete <name>` | Delete a VM |

## Security

- Network isolation: VMs use NAT with outbound-only traffic
- Resource limits: Configurable vCPUs, memory, and disk caps
- Host protection: Blocked access to host IP and localhost

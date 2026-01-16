# Hive

Hive is an easy way to craete reliable agenst with expanding toolkits. 

<p align="center">
  <img width="100%" alt="Hive Banner" src="https://storage.googleapis.com/aden-prod-assets/website/aden-title-card.png" />
</p>

[![Apache 2.0 License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/adenhq/hive/blob/main/LICENSE)
[![Y Combinator](https://img.shields.io/badge/Y%20Combinator-Aden-orange)](https://www.ycombinator.com/companies/aden)
[![Docker Pulls](https://img.shields.io/docker/pulls/adenhq/hive?logo=Docker&labelColor=%23528bff)](https://hub.docker.com/u/adenhq)
[![Discord](https://img.shields.io/discord/1172610340073242735?logo=discord&labelColor=%235462eb&logoColor=%23f5f5f5&color=%235462eb)](https://discord.com/invite/MXE49hrKDk)
[![Twitter Follow](https://img.shields.io/twitter/follow/teamaden?logo=X&color=%23f5f5f5)](https://x.com/aden_hq)
[![LinkedIn](https://custom-icon-badges.demolab.com/badge/LinkedIn-0A66C2?logo=linkedin-white&logoColor=fff)](https://www.linkedin.com/company/teamaden/)

## Overview

Hive provides advanced runtime control for your AI agents, enabling you to observe, intervene, and dynamically adjust agent behavior as it executes. By giving you real-time visibility and control, Hive helps you build more reliable AI systems—catching and correcting issues during execution rather than reacting after failures occur.

Visit [adenhq.com](https://adenhq.com) for complete documentation, examples, and guides.

## Quick Links

- **[Documentation](https://docs.adenhq.com/)** - Complete guides and API reference
- **[Self-Hosting Guide](https://docs.adenhq.com/getting-started/quickstart)** - Deploy Hive on your infrastructure
- **[Changelog](https://github.com/adenhq/hive/releases)** - Latest updates and releases
<!-- - **[Roadmap](https://adenhq.com/roadmap)** - Upcoming features and plans -->
- **[Report Issues](https://github.com/adenhq/hive/issues)** - Bug reports and feature requests

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (v20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2.0+)

### Installation

```bash
# Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive

# Copy and configure
cp config.yaml.example config.yaml

# Run setup and start services
npm run setup
docker compose up
```

**Access the application:**

- Dashboard: http://localhost:3000
- API: http://localhost:4000
- Health: http://localhost:4000/health

## Features

- **Observe** - Real-time visibility into agent execution, decisions, and performance
- **Metrics & Analytics** - Track costs, latency, and token usage with TimescaleDB
- **Cost Control** - Set budgets and policies to manage LLM spending
- **Real-time Events** - WebSocket streaming for live agent monitoring
- **Self-Hostable** - Deploy on your own infrastructure with full control
- **Production-Ready** - Built for scale and reliability

## Project Structure

```
hive/
├── honeycomb/          # Frontend (React + TypeScript + Vite)
├── hive/               # Backend (Node.js + TypeScript + Express)
├── docs/               # Documentation
├── scripts/            # Build and utility scripts
├── config.yaml.example # Configuration template
└── docker-compose.yml  # Container orchestration
```

## Development

### Local Development with Hot Reload

```bash
# Copy development overrides
cp docker-compose.override.yml.example docker-compose.override.yml

# Start with hot reload enabled
docker compose up
```

### Running Without Docker

```bash
# Install dependencies
npm install

# Generate environment files
npm run generate:env

# Start frontend (in honeycomb/)
cd honeycomb && npm run dev

# Start backend (in hive/)
cd hive && npm run dev
```

## Documentation

- **[Developer Guide](DEVELOPER.md)** - Comprehensive guide for developers
- [Getting Started](docs/getting-started.md) - Quick setup instructions
- [Configuration Guide](docs/configuration.md) - All configuration options
- [Architecture Overview](docs/architecture.md) - System design and structure

## Community & Support

We use [Discord](https://discord.com/invite/MXE49hrKDk) for support, feature requests, and community discussions.

- Discord - [Join our community](https://discord.com/invite/MXE49hrKDk)
- Twitter/X - [@adenhq](https://x.com/aden_hq)
- LinkedIn - [Company Page](https://www.linkedin.com/company/teamaden/)

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Join Our Team

**We're hiring!** Join us in engineering, research, and go-to-market roles.

[View Open Positions](https://jobs.adenhq.com/a8cec478-cdbc-473c-bbd4-f4b7027ec193/applicant)

## Security

For security concerns, please see [SECURITY.md](SECURITY.md).

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  Made with care by the <a href="https://adenhq.com">Aden</a> team
</p>

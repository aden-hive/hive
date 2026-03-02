# 🐝 Hive Web Dashboard

A modern web application for managing, monitoring, and controlling Hive AI agents with integration support for external services and APIs.

<p align="center">
  <img src="https://img.shields.io/badge/Status-Active-brightgreen" alt="Status" />
  <img src="https://img.shields.io/badge/Built%20with-React%20%2B%20Node.js-blue" alt="Stack" />
  <img src="https://img.shields.io/badge/License-Apache%202.0-orange" alt="License" />
</p>

## ✨ Features

### 🎯 Agent Management

- **List & Monitor** - View all exported Hive agents
- **Execute Agents** - Run agents with custom input
- **Real-time Feedback** - See execution results instantly
- **Agent Info** - Detailed information about each agent

### 🔌 Integration Management

- **Pre-built Integrations** - Slack, Email, Salesforce, HubSpot, Stripe, GitHub, Notion
- **Custom APIs** - Connect to any REST API
- **Credential Management** - Secure storage of API keys
- **Connection Testing** - Verify integration setup
- **Easy Configuration** - UI-based credential setup

### 📊 Dashboard & Monitoring

- **Live Status** - Backend and Hive health checks
- **Execution Timeline** - Agent run history and metrics
- **System Statistics** - Agent count and performance data
- **Real-time Updates** - Auto-refresh status

### 🏗️ Production Ready

- **Error Handling** - Comprehensive error messages
- **CORS Support** - Cross-origin requests enabled
- **Hot Reload** - Development server with auto-refresh
- **Docker Ready** - Containerized deployment
- **Scalable** - Built for growth

## 🚀 Quick Start

### Prerequisites

- Node.js 16+ and npm 7+
- Python 3.11+ (for Hive agents)
- Hive CLI installed
- Windows users: Use WSL 2 or Git Bash

### Installation

1. **Clone the repository:**

```bash
cd c:\Users\yokas\Desktop\m\hive\hive-web-dashboard
```

2. **Install backend dependencies:**

```bash
cd backend
npm install
```

3. **Install frontend dependencies:**

```bash
cd ../frontend
npm install
```

### Running Locally

**Terminal 1 - Backend:**

```bash
cd backend
npm run dev
```

**Terminal 2 - Frontend:**

```bash
cd frontend
npm run dev
```

Open your browser to `http://localhost:5173`

## 📋 Project Structure

```
hive-web-dashboard/
├── backend/              # Express.js API server
│   ├── src/
│   │   ├── server.js     # Express app
│   │   ├── controllers/  # Request handlers
│   │   ├── services/     # Business logic
│   │   └── routes/       # API endpoints
│   ├── package.json
│   └── README.md
│
├── frontend/             # React + Vite UI
│   ├── src/
│   │   ├── components/   # React components
│   │   ├── App.jsx       # Main app
│   │   └── index.css     # Styles
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
│
├── SETUP.md              # Complete setup guide
├── INTEGRATION_GUIDE.md  # Integration development
└── README.md             # This file
```

## 🔌 Integrations

Hive Dashboard supports integrations with popular business services:

### Available Now

- **Slack** - Send notifications to channels
- **Email** - SMTP and email service integration
- **Custom API** - Connect to any REST endpoint

### Coming Soon

- Salesforce CRM
- HubSpot Marketing
- Stripe Payments
- GitHub Repository
- Notion Database

### Adding Integrations

See `INTEGRATION_GUIDE.md` for:

- How to configure integrations
- Building custom integrations
- Contributing new integration support
- Security best practices

## 🎨 UI Components

### Tabs

1. **📊 Status** - Backend and Hive health
2. **🤖 Agents** - List and manage agents
3. **▶️ Run Agent** - Execute agents with JSON input
4. **🔌 Integrations** - Manage external service connections
5. **📈 Dashboard** - Stats and performance charts

### Design

- **Responsive Layout** - Works on desktop, tablet, mobile
- **Modern UI** - Gradient design with smooth animations
- **Accessible** - Keyboard navigation and screen reader support
- **Dark Mode Ready** - Can be extended with theme support

## 📚 API Reference

### Hive Agent Endpoints

| Method | Endpoint                 | Description          |
| ------ | ------------------------ | -------------------- |
| GET    | `/api/health`            | Backend health check |
| GET    | `/api/hive/status`       | Hive system status   |
| GET    | `/api/hive/agents`       | List all agents      |
| GET    | `/api/hive/agents/:name` | Get agent info       |
| POST   | `/api/hive/run`          | Run an agent         |

### Integration Endpoints

| Method | Endpoint                            | Description            |
| ------ | ----------------------------------- | ---------------------- |
| GET    | `/api/integrations`                 | List all integrations  |
| GET    | `/api/integrations/:name`           | Get integration config |
| POST   | `/api/integrations/:name/configure` | Save credentials       |
| POST   | `/api/integrations/:name/test`      | Test connection        |
| DELETE | `/api/integrations/:name`           | Remove integration     |

## 🔒 Security

- **Credential Encryption** - API keys stored securely
- **CORS Enabled** - Cross-origin requests allowed
- **Input Validation** - All user inputs validated
- **Error Handling** - Sensitive info never exposed
- **HTTPS Ready** - SSL/TLS support for production

See `SETUP.md` for security recommendations.

## 📖 Documentation

- **[SETUP.md](./SETUP.md)** - Complete setup and deployment guide
- **[INTEGRATION_GUIDE.md](./INTEGRATION_GUIDE.md)** - Building integrations
- **[backend/README.md](./backend/README.md)** - Backend API docs
- **[frontend/README.md](./frontend/README.md)** - Frontend docs

## 🛠️ Development

### Tech Stack

**Backend:**

- Node.js 18+
- Express.js 4
- CORS middleware
- Dotenv for configuration

**Frontend:**

- React 18+
- Vite 5 (fast build tool)
- Axios (HTTP client)
- CSS3 with gradients and animations

### Available Scripts

**Backend:**

```bash
npm run dev      # Start development server
npm start        # Start production server
npm test         # Run tests (when added)
```

**Frontend:**

```bash
npm run dev      # Start dev server
npm run build    # Build for production
npm run preview  # Preview production build
```

## 🐳 Docker Deployment

```bash
# Build image
docker build -t hive-dashboard:latest .

# Run container
docker run -p 5000:5000 \
  -e HIVE_HOME=/hive \
  hive-dashboard:latest
```

See `SETUP.md` for detailed Docker and production deployment instructions.

## 🚨 Troubleshooting

### Backend won't start

```bash
cd backend
npm install
```

### Can't find hive command

- Ensure Hive CLI is in your PATH
- Use WSL or Git Bash on Windows

### Frontend can't reach backend

- Verify backend is running on port 5000
- Check CORS is enabled
- Review browser console errors

See `SETUP.md` for more troubleshooting.

## 🤝 Contributing

We welcome contributions! To contribute:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

For integration contributions, see `INTEGRATION_GUIDE.md`.

## 📄 License

Apache License 2.0 - See LICENSE file for details.

## 🔗 Links

- **Hive Repository** - https://github.com/adenhq/hive
- **Hive Documentation** - https://docs.adenhq.com
- **Discord Community** - https://discord.gg/...
- **GitHub Issues** - https://github.com/adenhq/hive/issues

## 🎓 Learning Resources

- **[Hive Codebase Guides](../INDEX_ALL_GUIDES.md)** - Deep dive into Hive architecture
- **[Quick Reference](../QUICK_REFERENCE.md)** - Copy-paste patterns and examples
- **[Architecture Diagrams](../ARCHITECTURE_VISUAL.md)** - Visual system design

## ❓ FAQ

**Q: Do I need to know Python to use this dashboard?**
A: No! The dashboard provides a visual interface for running pre-built agents. However, writing custom agents requires Python.

**Q: Can I run this on Windows?**
A: Yes, but it's recommended to use WSL 2 or Git Bash for best compatibility.

**Q: How do I add new integrations?**
A: See `INTEGRATION_GUIDE.md` for step-by-step instructions.

**Q: Can I deploy this to production?**
A: Yes! See `SETUP.md` for Docker and production deployment guides.

**Q: Is this open source?**
A: Yes, Apache 2.0 license. Contributions are welcome!

## 📞 Support

- **Questions?** Open an issue on GitHub
- **Found a bug?** Submit a bug report
- **Have an idea?** Start a discussion
- **Need help?** Check the documentation

---

**Made with ❤️ by the Aden team**

Build autonomous, reliable, self-improving AI agents without hardcoding workflows. 🚀

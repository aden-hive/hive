<p align="center">
  <img width="100%" alt="Hive Banner" src="https://storage.googleapis.com/aden-prod-assets/website/aden-title-card.png" />
</p>

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh-CN.md">简体中文</a> |
  <a href="README.es.md">Español</a> |
  <a href="README.pt.md">Português</a> |
  <a href="README.ja.md">日本語</a> |
  <a href="README.ru.md">Русский</a>
</p>

[![Apache 2.0 License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/adenhq/hive/blob/main/LICENSE)
[![Y Combinator](https://img.shields.io/badge/Y%20Combinator-Aden-orange)](https://www.ycombinator.com/companies/aden)
[![Docker Pulls](https://img.shields.io/docker/pulls/adenhq/hive?logo=Docker&labelColor=%23528bff)](https://hub.docker.com/u/adenhq)
[![Discord](https://img.shields.io/discord/1172610340073242735?logo=discord&labelColor=%235462eb&logoColor=%23f5f5f5&color=%235462eb)](https://discord.com/invite/MXE49hrKDk)
[![Twitter Follow](https://img.shields.io/twitter/follow/teamaden?logo=X&color=%23f5f5f5)](https://x.com/aden_hq)
[![LinkedIn](https://custom-icon-badges.demolab.com/badge/LinkedIn-0A66C2?logo=linkedin-white&logoColor=fff)](https://www.linkedin.com/company/teamaden/)

<p align="center">
  <img src="https://img.shields.io/badge/AI_Agents-Self--Improving-brightgreen?style=flat-square" alt="AI Agents" />
  <img src="https://img.shields.io/badge/Multi--Agent-Systems-blue?style=flat-square" alt="Multi-Agent" />
  <img src="https://img.shields.io/badge/Goal--Driven-Development-purple?style=flat-square" alt="Goal-Driven" />
  <img src="https://img.shields.io/badge/Human--in--the--Loop-orange?style=flat-square" alt="HITL" />
  <img src="https://img.shields.io/badge/Production--Ready-red?style=flat-square" alt="Production" />
</p>
<p align="center">
  <img src="https://img.shields.io/badge/OpenAI-supported-412991?style=flat-square&logo=openai" alt="OpenAI" />
  <img src="https://img.shields.io/badge/Anthropic-supported-d4a574?style=flat-square" alt="Anthropic" />
  <img src="https://img.shields.io/badge/Google_Gemini-supported-4285F4?style=flat-square&logo=google" alt="Gemini" />
  <img src="https://img.shields.io/badge/MCP-19_Tools-00ADD8?style=flat-square" alt="MCP" />
</p>

## 概述

构建可靠的、自我改进的 AI 智能体，无需硬编码工作流。通过与编码智能体对话来定义目标，框架会生成带有动态创建连接代码的节点图。当出现问题时，框架会捕获故障数据，通过编码智能体进化智能体，并重新部署。内置的人机协作节点、凭证管理和实时监控让您在保持适应性的同时拥有完全控制权。

访问 [adenhq.com](https://adenhq.com) 获取完整文档、示例和指南。

## 什么是 Aden

<p align="center">
  <img width="100%" alt="Aden Architecture" src="docs/assets/aden-architecture-diagram.jpg" />
</p>

Aden 是一个用于构建、部署、运营和适应 AI 智能体的平台：

- **构建** - 编码智能体根据自然语言目标生成专业的工作智能体（销售、营销、运营）
- **部署** - 无头部署，支持 CI/CD 集成和完整的 API 生命周期管理
- **运营** - 实时监控、可观测性和运行时护栏确保智能体可靠运行
- **适应** - 持续评估、监督和适应确保智能体随时间改进
- **基础设施** - 共享内存、LLM 集成、工具和技能为每个智能体提供支持

## 快速链接

- **[文档](https://docs.adenhq.com/)** - 完整指南和 API 参考
- **[自托管指南](https://docs.adenhq.com/getting-started/quickstart)** - 在您的基础设施上部署 Hive
- **[更新日志](https://github.com/adenhq/hive/releases)** - 最新更新和版本
- **[报告问题](https://github.com/adenhq/hive/issues)** - Bug 报告和功能请求

## 快速开始

### 前置要求

- [Docker](https://docs.docker.com/get-docker/) (v20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2.0+)

### 安装

```bash
# 克隆仓库
git clone https://github.com/adenhq/hive.git
cd hive

# 复制并配置
cp config.yaml.example config.yaml

# 运行设置并启动服务
npm run setup
docker compose up
```

**访问应用：**

- 仪表板：http://localhost:3000
- API：http://localhost:4000
- 健康检查：http://localhost:4000/health

## 功能特性

- **目标驱动开发** - 用自然语言定义目标；编码智能体生成智能体图和连接代码来实现它们
- **自适应智能体** - 框架捕获故障，更新目标并更新智能体图
- **动态节点连接** - 没有预定义边；连接代码由任何有能力的 LLM 根据您的目标生成
- **SDK 封装节点** - 每个节点开箱即用地获得共享内存、本地 RLM 内存、监控、工具和 LLM 访问
- **人机协作** - 干预节点暂停执行以等待人工输入，支持可配置的超时和升级
- **实时可观测性** - WebSocket 流式传输用于实时监控智能体执行、决策和节点间通信
- **成本与预算控制** - 设置支出限制、节流和自动模型降级策略
- **生产就绪** - 可自托管，为规模和可靠性而构建

## 为什么选择 Aden

传统智能体框架要求您手动设计工作流、定义智能体交互并被动处理故障。Aden 颠覆了这一范式——**您描述结果，系统自动构建自己**。

### Aden 的优势

| 传统框架 | Aden |
|----------|------|
| 硬编码智能体工作流 | 用自然语言描述目标 |
| 手动定义图 | 自动生成智能体图 |
| 被动错误处理 | 主动自我进化 |
| 静态工具配置 | 动态 SDK 封装节点 |
| 单独设置监控 | 内置实时可观测性 |
| DIY 预算管理 | 集成成本控制和降级 |

### 工作原理

1. **定义目标** → 用简单英语描述您想要实现的目标
2. **编码智能体生成** → 创建智能体图、连接代码和测试用例
3. **工作节点执行** → SDK 封装节点以完全可观测性和工具访问运行
4. **控制平面监控** → 实时指标、预算执行、策略管理
5. **自我改进** → 失败时，系统进化图并自动重新部署

## 项目结构

```
hive/
├── honeycomb/          # 前端 (React + TypeScript + Vite)
├── hive/               # 后端 (Node.js + TypeScript + Express)
├── docs/               # 文档
├── scripts/            # 构建和实用脚本
├── config.yaml.example # 配置模板
└── docker-compose.yml  # 容器编排
```

## 开发

### 带热重载的本地开发

```bash
# 复制开发覆盖配置
cp docker-compose.override.yml.example docker-compose.override.yml

# 启用热重载启动
docker compose up
```

### 不使用 Docker 运行

```bash
# 安装依赖
npm install

# 生成环境文件
npm run generate:env

# 启动前端（在 honeycomb/ 目录）
cd honeycomb && npm run dev

# 启动后端（在 hive/ 目录）
cd hive && npm run dev
```

## 文档

- **[开发者指南](DEVELOPER.md)** - 开发者综合指南
- [入门指南](docs/getting-started.md) - 快速设置说明
- [配置指南](docs/configuration.md) - 所有配置选项
- [架构概述](docs/architecture.md) - 系统设计和结构

## 路线图

Aden 智能体框架旨在帮助开发者构建面向结果的、自适应的智能体。请在此查看我们的路线图：

[ROADMAP.md](ROADMAP.md)

## 社区与支持

我们使用 [Discord](https://discord.com/invite/MXE49hrKDk) 进行支持、功能请求和社区讨论。

- Discord - [加入我们的社区](https://discord.com/invite/MXE49hrKDk)
- Twitter/X - [@adenhq](https://x.com/aden_hq)
- LinkedIn - [公司主页](https://www.linkedin.com/company/teamaden/)

## 贡献

我们欢迎贡献！请参阅 [CONTRIBUTING.md](CONTRIBUTING.md) 了解指南。

1. Fork 仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

## 加入我们的团队

**我们正在招聘！** 加入我们的工程、研究和市场推广团队。

[查看开放职位](https://jobs.adenhq.com/a8cec478-cdbc-473c-bbd4-f4b7027ec193/applicant)

## 安全

有关安全问题，请参阅 [SECURITY.md](SECURITY.md)。

## 许可证

本项目采用 Apache License 2.0 许可证 - 详情请参阅 [LICENSE](LICENSE) 文件。

## 常见问题 (FAQ)

**问：Aden 是否依赖 LangChain 或其他智能体框架？**

不。Aden 从头开始构建，不依赖 LangChain、CrewAI 或其他智能体框架。该框架设计精简灵活，动态生成智能体图而非依赖预定义组件。

**问：Aden 支持哪些 LLM 提供商？**

Aden 开箱即用支持 OpenAI（GPT-4、GPT-4o）、Anthropic（Claude 模型）和 Google Gemini。架构通过 SDK 抽象实现提供商无关，LiteLLM 集成在路线图中以扩展模型支持。

**问：Aden 是开源的吗？**

是的，Aden 在 Apache License 2.0 下完全开源。我们积极鼓励社区贡献和协作。

**问：Aden 支持哪些部署选项？**

Aden 开箱即用支持 Docker Compose 部署，包括生产和开发配置。自托管部署可在任何支持 Docker 的基础设施上运行。云部署选项和 Kubernetes 就绪配置在路线图中。

**问：Aden 能处理复杂的生产级用例吗？**

可以。Aden 明确为生产环境设计，具有自动故障恢复、实时可观测性、成本控制和水平扩展支持等功能。该框架可处理简单自动化和复杂的多智能体工作流。

**问：Aden 支持人机协作工作流吗？**

是的，Aden 通过干预节点完全支持人机协作工作流，这些节点会暂停执行以等待人工输入。包括可配置的超时和升级策略，实现人类专家与 AI 智能体的无缝协作。

**问：如何为 Aden 做贡献？**

欢迎贡献！Fork 仓库，创建功能分支，实现更改，然后提交 pull request。详细指南请参阅 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

<p align="center">
  用 🔥 热情打造于旧金山
</p>

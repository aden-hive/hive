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

## Visão Geral

Construa agentes de IA confiáveis e auto-aperfeiçoáveis sem codificar fluxos de trabalho. Defina seu objetivo através de uma conversa com um agente de codificação, e o framework gera um grafo de nós com código de conexão criado dinamicamente. Quando algo quebra, o framework captura dados de falha, evolui o agente através do agente de codificação e reimplanta. Nós de intervenção humana integrados, gerenciamento de credenciais e monitoramento em tempo real dão a você controle sem sacrificar a adaptabilidade.

Visite [adenhq.com](https://adenhq.com) para documentação completa, exemplos e guias.

## O que é Aden

<p align="center">
  <img width="100%" alt="Aden Architecture" src="docs/assets/aden-architecture-diagram.jpg" />
</p>

Aden é uma plataforma para construir, implantar, operar e adaptar agentes de IA:

- **Construir** - Um Agente de Codificação gera Agentes de Trabalho especializados (Vendas, Marketing, Operações) a partir de objetivos em linguagem natural
- **Implantar** - Implantação headless com integração CI/CD e gerenciamento completo do ciclo de vida de API
- **Operar** - Monitoramento em tempo real, observabilidade e guardrails de runtime mantêm os agentes confiáveis
- **Adaptar** - Avaliação contínua, supervisão e adaptação garantem que os agentes melhorem ao longo do tempo
- **Infraestrutura** - Memória compartilhada, integrações LLM, ferramentas e habilidades alimentam cada agente

## Links Rápidos

- **[Documentação](https://docs.adenhq.com/)** - Guias completos e referência de API
- **[Guia de Auto-Hospedagem](https://docs.adenhq.com/getting-started/quickstart)** - Implante o Hive em sua infraestrutura
- **[Changelog](https://github.com/adenhq/hive/releases)** - Últimas atualizações e versões
- **[Reportar Problemas](https://github.com/adenhq/hive/issues)** - Relatórios de bugs e solicitações de funcionalidades

## Início Rápido

### Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) (v20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2.0+)

### Instalação

```bash
# Clonar o repositório
git clone https://github.com/adenhq/hive.git
cd hive

# Copiar e configurar
cp config.yaml.example config.yaml

# Executar configuração e iniciar serviços
npm run setup
docker compose up
```

**Acessar a aplicação:**

- Dashboard: http://localhost:3000
- API: http://localhost:4000
- Health: http://localhost:4000/health

## Funcionalidades

- **Desenvolvimento Orientado a Objetivos** - Defina objetivos em linguagem natural; o agente de codificação gera o grafo de agentes e código de conexão para alcançá-los
- **Agentes Auto-Adaptáveis** - Framework captura falhas, atualiza objetivos e atualiza o grafo de agentes
- **Conexões de Nós Dinâmicas** - Sem arestas predefinidas; código de conexão é gerado por qualquer LLM capaz baseado em seus objetivos
- **Nós Envolvidos em SDK** - Cada nó recebe memória compartilhada, memória RLM local, monitoramento, ferramentas e acesso LLM prontos para uso
- **Humano no Loop** - Nós de intervenção que pausam a execução para entrada humana com timeouts e escalonamento configuráveis
- **Observabilidade em Tempo Real** - Streaming WebSocket para monitoramento ao vivo de execução de agentes, decisões e comunicação entre nós
- **Controle de Custo e Orçamento** - Defina limites de gastos, throttles e políticas de degradação automática de modelo
- **Pronto para Produção** - Auto-hospedável, construído para escala e confiabilidade

## Por que Aden

Frameworks de agentes tradicionais exigem que você projete manualmente fluxos de trabalho, defina interações de agentes e lide com falhas reativamente. Aden inverte esse paradigma—**você descreve resultados, e o sistema se constrói sozinho**.

### A Vantagem Aden

| Frameworks Tradicionais | Aden |
|-------------------------|------|
| Codificar fluxos de trabalho de agentes | Descrever objetivos em linguagem natural |
| Definição manual de grafos | Grafos de agentes auto-gerados |
| Tratamento reativo de erros | Auto-evolução proativa |
| Configurações de ferramentas estáticas | Nós dinâmicos envolvidos em SDK |
| Configuração de monitoramento separada | Observabilidade em tempo real integrada |
| Gerenciamento de orçamento DIY | Controles de custo e degradação integrados |

### Como Funciona

1. **Defina Seu Objetivo** → Descreva o que você quer alcançar em português simples
2. **Agente de Codificação Gera** → Cria o grafo de agentes, código de conexão e casos de teste
3. **Workers Executam** → Nós envolvidos em SDK executam com observabilidade completa e acesso a ferramentas
4. **Plano de Controle Monitora** → Métricas em tempo real, aplicação de orçamento, gerenciamento de políticas
5. **Auto-Aperfeiçoamento** → Em caso de falha, o sistema evolui o grafo e reimplanta automaticamente

## Estrutura do Projeto

```
hive/
├── honeycomb/          # Frontend (React + TypeScript + Vite)
├── hive/               # Backend (Node.js + TypeScript + Express)
├── docs/               # Documentação
├── scripts/            # Scripts de build e utilitários
├── config.yaml.example # Template de configuração
└── docker-compose.yml  # Orquestração de containers
```

## Desenvolvimento

### Desenvolvimento Local com Hot Reload

```bash
# Copiar overrides de desenvolvimento
cp docker-compose.override.yml.example docker-compose.override.yml

# Iniciar com hot reload habilitado
docker compose up
```

### Executar Sem Docker

```bash
# Instalar dependências
npm install

# Gerar arquivos de ambiente
npm run generate:env

# Iniciar frontend (em honeycomb/)
cd honeycomb && npm run dev

# Iniciar backend (em hive/)
cd hive && npm run dev
```

## Documentação

- **[Guia do Desenvolvedor](DEVELOPER.md)** - Guia abrangente para desenvolvedores
- [Começando](docs/getting-started.md) - Instruções de configuração rápida
- [Guia de Configuração](docs/configuration.md) - Todas as opções de configuração
- [Visão Geral da Arquitetura](docs/architecture.md) - Design e estrutura do sistema

## Roadmap

O Aden Agent Framework visa ajudar desenvolvedores a construir agentes auto-adaptativos orientados a resultados. Encontre nosso roadmap aqui:

[ROADMAP.md](ROADMAP.md)

## Comunidade e Suporte

Usamos [Discord](https://discord.com/invite/MXE49hrKDk) para suporte, solicitações de funcionalidades e discussões da comunidade.

- Discord - [Junte-se à nossa comunidade](https://discord.com/invite/MXE49hrKDk)
- Twitter/X - [@adenhq](https://x.com/aden_hq)
- LinkedIn - [Página da Empresa](https://www.linkedin.com/company/teamaden/)

## Contribuindo

Aceitamos contribuições! Por favor, consulte [CONTRIBUTING.md](CONTRIBUTING.md) para diretrizes.

1. Faça fork do repositório
2. Crie sua branch de funcionalidade (`git checkout -b feature/amazing-feature`)
3. Faça commit das suas alterações (`git commit -m 'Add amazing feature'`)
4. Faça push para a branch (`git push origin feature/amazing-feature`)
5. Abra um Pull Request

## Junte-se ao Nosso Time

**Estamos contratando!** Junte-se a nós em funções de engenharia, pesquisa e go-to-market.

[Ver Posições Abertas](https://jobs.adenhq.com/a8cec478-cdbc-473c-bbd4-f4b7027ec193/applicant)

## Segurança

Para questões de segurança, por favor consulte [SECURITY.md](SECURITY.md).

## Licença

Este projeto está licenciado sob a Licença Apache 2.0 - veja o arquivo [LICENSE](LICENSE) para detalhes.

## Perguntas Frequentes (FAQ)

**P: O Aden depende do LangChain ou outros frameworks de agentes?**

Não. O Aden é construído do zero sem dependências do LangChain, CrewAI ou outros frameworks de agentes. O framework é projetado para ser leve e flexível, gerando grafos de agentes dinamicamente em vez de depender de componentes predefinidos.

**P: Quais provedores de LLM o Aden suporta?**

O Aden suporta OpenAI (GPT-4, GPT-4o), Anthropic (modelos Claude) e Google Gemini prontos para uso. A arquitetura é agnóstica de provedor através da abstração do SDK, com integração LiteLLM no roadmap para suporte expandido de modelos.

**P: O Aden é open-source?**

Sim, o Aden é totalmente open-source sob a Licença Apache 2.0. Incentivamos ativamente contribuições e colaboração da comunidade.

**P: Quais opções de implantação o Aden suporta?**

O Aden suporta implantação Docker Compose pronta para uso, com configurações de produção e desenvolvimento. Implantações auto-hospedadas funcionam em qualquer infraestrutura que suporte Docker. Opções de implantação em nuvem e configurações prontas para Kubernetes estão no roadmap.

**P: O Aden pode lidar com casos de uso complexos em escala de produção?**

Sim. O Aden é explicitamente projetado para ambientes de produção com recursos como recuperação automática de falhas, observabilidade em tempo real, controles de custo e suporte a escalonamento horizontal. O framework lida tanto com automações simples quanto com fluxos de trabalho complexos multi-agente.

**P: O Aden suporta fluxos de trabalho com humano no loop?**

Sim, o Aden suporta totalmente fluxos de trabalho com humano no loop através de nós de intervenção que pausam a execução para entrada humana. Estes incluem timeouts configuráveis e políticas de escalonamento, permitindo colaboração perfeita entre especialistas humanos e agentes de IA.

**P: Como posso contribuir para o Aden?**

Contribuições são bem-vindas! Faça fork do repositório, crie sua branch de funcionalidade, implemente suas alterações e envie um pull request. Consulte [CONTRIBUTING.md](CONTRIBUTING.md) para diretrizes detalhadas.

---

<p align="center">
  Feito com 🔥 Paixão em San Francisco
</p>

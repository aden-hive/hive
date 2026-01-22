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

## Descripción General

Construye agentes de IA confiables y auto-mejorables sin codificar flujos de trabajo. Define tu objetivo a través de una conversación con un agente de codificación, y el framework genera un grafo de nodos con código de conexión creado dinámicamente. Cuando algo falla, el framework captura los datos del error, evoluciona el agente a través del agente de codificación y lo vuelve a desplegar. Los nodos de intervención humana integrados, la gestión de credenciales y el monitoreo en tiempo real te dan control sin sacrificar la adaptabilidad.

Visita [adenhq.com](https://adenhq.com) para documentación completa, ejemplos y guías.

## ¿Qué es Aden?

<p align="center">
  <img width="100%" alt="Aden Architecture" src="docs/assets/aden-architecture-diagram.jpg" />
</p>

Aden es una plataforma para construir, desplegar, operar y adaptar agentes de IA:

- **Construir** - Un Agente de Codificación genera Agentes de Trabajo especializados (Ventas, Marketing, Operaciones) a partir de objetivos en lenguaje natural
- **Desplegar** - Despliegue headless con integración CI/CD y gestión completa del ciclo de vida de API
- **Operar** - Monitoreo en tiempo real, observabilidad y guardarraíles de ejecución mantienen los agentes confiables
- **Adaptar** - Evaluación continua, supervisión y adaptación aseguran que los agentes mejoren con el tiempo
- **Infraestructura** - Memoria compartida, integraciones LLM, herramientas y habilidades impulsan cada agente

## Enlaces Rápidos

- **[Documentación](https://docs.adenhq.com/)** - Guías completas y referencia de API
- **[Guía de Auto-Hospedaje](https://docs.adenhq.com/getting-started/quickstart)** - Despliega Hive en tu infraestructura
- **[Registro de Cambios](https://github.com/adenhq/hive/releases)** - Últimas actualizaciones y versiones
- **[Reportar Problemas](https://github.com/adenhq/hive/issues)** - Reportes de bugs y solicitudes de funciones

## Inicio Rápido

### Prerrequisitos

- [Docker](https://docs.docker.com/get-docker/) (v20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2.0+)

### Instalación

```bash
# Clonar el repositorio
git clone https://github.com/adenhq/hive.git
cd hive

# Copiar y configurar
cp config.yaml.example config.yaml

# Ejecutar configuración e iniciar servicios
npm run setup
docker compose up
```

**Acceder a la aplicación:**

- Panel de Control: http://localhost:3000
- API: http://localhost:4000
- Salud: http://localhost:4000/health

## Características

- **Desarrollo Orientado a Objetivos** - Define objetivos en lenguaje natural; el agente de codificación genera el grafo de agentes y el código de conexión para lograrlos
- **Agentes Auto-Adaptables** - El framework captura fallos, actualiza objetivos y actualiza el grafo de agentes
- **Conexiones de Nodos Dinámicas** - Sin aristas predefinidas; el código de conexión es generado por cualquier LLM capaz basado en tus objetivos
- **Nodos Envueltos en SDK** - Cada nodo obtiene memoria compartida, memoria RLM local, monitoreo, herramientas y acceso LLM de serie
- **Humano en el Bucle** - Nodos de intervención que pausan la ejecución para entrada humana con tiempos de espera y escalación configurables
- **Observabilidad en Tiempo Real** - Streaming WebSocket para monitoreo en vivo de ejecución de agentes, decisiones y comunicación entre nodos
- **Control de Costos y Presupuesto** - Establece límites de gasto, limitadores y políticas de degradación automática de modelos
- **Listo para Producción** - Auto-hospedable, construido para escala y confiabilidad

## Por Qué Aden

Los frameworks de agentes tradicionales requieren que diseñes manualmente flujos de trabajo, definas interacciones de agentes y manejes fallos de forma reactiva. Aden invierte este paradigma—**describes resultados, y el sistema se construye solo**.

### La Ventaja de Aden

| Frameworks Tradicionales | Aden |
|--------------------------|------|
| Codificar flujos de trabajo de agentes | Describir objetivos en lenguaje natural |
| Definición manual de grafos | Grafos de agentes auto-generados |
| Manejo reactivo de errores | Auto-evolución proactiva |
| Configuraciones de herramientas estáticas | Nodos dinámicos envueltos en SDK |
| Configuración de monitoreo separada | Observabilidad en tiempo real integrada |
| Gestión de presupuesto DIY | Controles de costos y degradación integrados |

### Cómo Funciona

1. **Define Tu Objetivo** → Describe lo que quieres lograr en español simple
2. **El Agente de Codificación Genera** → Crea el grafo de agentes, código de conexión y casos de prueba
3. **Los Trabajadores Ejecutan** → Los nodos envueltos en SDK se ejecutan con observabilidad completa y acceso a herramientas
4. **El Plano de Control Monitorea** → Métricas en tiempo real, aplicación de presupuesto, gestión de políticas
5. **Auto-Mejora** → En caso de fallo, el sistema evoluciona el grafo y lo vuelve a desplegar automáticamente

## Estructura del Proyecto

```
hive/
├── honeycomb/          # Frontend (React + TypeScript + Vite)
├── hive/               # Backend (Node.js + TypeScript + Express)
├── docs/               # Documentación
├── scripts/            # Scripts de construcción y utilidades
├── config.yaml.example # Plantilla de configuración
└── docker-compose.yml  # Orquestación de contenedores
```

## Desarrollo

### Desarrollo Local con Recarga en Caliente

```bash
# Copiar sobrescrituras de desarrollo
cp docker-compose.override.yml.example docker-compose.override.yml

# Iniciar con recarga en caliente habilitada
docker compose up
```

### Ejecutar Sin Docker

```bash
# Instalar dependencias
npm install

# Generar archivos de entorno
npm run generate:env

# Iniciar frontend (en honeycomb/)
cd honeycomb && npm run dev

# Iniciar backend (en hive/)
cd hive && npm run dev
```

## Documentación

- **[Guía del Desarrollador](DEVELOPER.md)** - Guía completa para desarrolladores
- [Primeros Pasos](docs/getting-started.md) - Instrucciones de configuración rápida
- [Guía de Configuración](docs/configuration.md) - Todas las opciones de configuración
- [Visión General de Arquitectura](docs/architecture.md) - Diseño y estructura del sistema

## Hoja de Ruta

El Framework de Agentes Aden tiene como objetivo ayudar a los desarrolladores a construir agentes auto-adaptativos orientados a resultados. Encuentra nuestra hoja de ruta aquí:

[ROADMAP.md](ROADMAP.md)

## Comunidad y Soporte

Usamos [Discord](https://discord.com/invite/MXE49hrKDk) para soporte, solicitudes de funciones y discusiones de la comunidad.

- Discord - [Únete a nuestra comunidad](https://discord.com/invite/MXE49hrKDk)
- Twitter/X - [@adenhq](https://x.com/aden_hq)
- LinkedIn - [Página de la Empresa](https://www.linkedin.com/company/teamaden/)

## Contribuir

¡Damos la bienvenida a las contribuciones! Por favor consulta [CONTRIBUTING.md](CONTRIBUTING.md) para las directrices.

1. Haz fork del repositorio
2. Crea tu rama de funcionalidad (`git checkout -b feature/amazing-feature`)
3. Haz commit de tus cambios (`git commit -m 'Add amazing feature'`)
4. Haz push a la rama (`git push origin feature/amazing-feature`)
5. Abre un Pull Request

## Únete a Nuestro Equipo

**¡Estamos contratando!** Únete a nosotros en roles de ingeniería, investigación y comercialización.

[Ver Posiciones Abiertas](https://jobs.adenhq.com/a8cec478-cdbc-473c-bbd4-f4b7027ec193/applicant)

## Seguridad

Para preocupaciones de seguridad, por favor consulta [SECURITY.md](SECURITY.md).

## Licencia

Este proyecto está licenciado bajo la Licencia Apache 2.0 - consulta el archivo [LICENSE](LICENSE) para más detalles.

## Preguntas Frecuentes (FAQ)

**P: ¿Aden depende de LangChain u otros frameworks de agentes?**

No. Aden está construido desde cero sin dependencias de LangChain, CrewAI u otros frameworks de agentes. El framework está diseñado para ser ligero y flexible, generando grafos de agentes dinámicamente en lugar de depender de componentes predefinidos.

**P: ¿Qué proveedores de LLM soporta Aden?**

Aden soporta OpenAI (GPT-4, GPT-4o), Anthropic (modelos Claude) y Google Gemini de serie. La arquitectura es agnóstica al proveedor a través de la abstracción del SDK, con integración de LiteLLM en la hoja de ruta para soporte expandido de modelos.

**P: ¿Aden es de código abierto?**

Sí, Aden es completamente de código abierto bajo la Licencia Apache 2.0. Fomentamos activamente las contribuciones y colaboración de la comunidad.

**P: ¿Qué opciones de despliegue soporta Aden?**

Aden soporta despliegue con Docker Compose de serie, con configuraciones tanto de producción como de desarrollo. Los despliegues auto-hospedados funcionan en cualquier infraestructura que soporte Docker. Las opciones de despliegue en la nube y configuraciones listas para Kubernetes están en la hoja de ruta.

**P: ¿Puede Aden manejar casos de uso complejos a escala de producción?**

Sí. Aden está explícitamente diseñado para entornos de producción con características como recuperación automática de fallos, observabilidad en tiempo real, controles de costos y soporte de escalado horizontal. El framework maneja tanto automatizaciones simples como flujos de trabajo complejos multi-agente.

**P: ¿Aden soporta flujos de trabajo con humano en el bucle?**

Sí, Aden soporta completamente flujos de trabajo con humano en el bucle a través de nodos de intervención que pausan la ejecución para entrada humana. Estos incluyen tiempos de espera configurables y políticas de escalación, permitiendo colaboración fluida entre expertos humanos y agentes de IA.

**P: ¿Cómo puedo contribuir a Aden?**

¡Las contribuciones son bienvenidas! Haz fork del repositorio, crea tu rama de funcionalidad, implementa tus cambios y envía un pull request. Consulta [CONTRIBUTING.md](CONTRIBUTING.md) para directrices detalladas.

---

<p align="center">
  Hecho con 🔥 Pasión en San Francisco
</p>

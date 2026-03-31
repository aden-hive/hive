<p align="center">
  <img width="100%" alt="Hive Banner" src="https://github.com/user-attachments/assets/a027429b-5d3c-4d34-88e4-0feaeaabbab3" />
</p>

<p align="center">
  <a href="../../README.md">English</a> |
  <a href="zh-CN.md">简体中文</a> |
  <a href="es.md">Español</a> |
  <a href="hi.md">हिन्दी</a> |
  <a href="pt.md">Português</a> |
  <a href="ja.md">日本語</a> |
  <a href="ru.md">Русский</a> |
  <a href="ko.md">한국어</a> |
  <a href="id.md">Bahasa Indonesia</a>
</p>

<p align="center">
  <a href="https://github.com/aden-hive/hive/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="Apache 2.0 License" /></a>
  <a href="https://www.ycombinator.com/companies/aden"><img src="https://img.shields.io/badge/Y%20Combinator-Aden-orange" alt="Y Combinator" /></a>
  <a href="https://discord.com/invite/MXE49hrKDk"><img src="https://img.shields.io/discord/1172610340073242735?logo=discord&labelColor=%235462eb&logoColor=%23f5f5f5&color=%235462eb" alt="Discord" /></a>
  <a href="https://x.com/aden_hq"><img src="https://img.shields.io/twitter/follow/teamaden?logo=X&color=%23f5f5f5" alt="Twitter Follow" /></a>
  <a href="https://www.linkedin.com/company/teamaden/"><img src="https://custom-icon-badges.demolab.com/badge/LinkedIn-0A66C2?logo=linkedin-white&logoColor=fff" alt="LinkedIn" /></a>
  <img src="https://img.shields.io/badge/MCP-102_Tools-00ADD8?style=flat-square" alt="MCP" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/AI_Agents-Self--Improving-brightgreen?style=flat-square" alt="AI Agents" />
  <img src="https://img.shields.io/badge/Multi--Agent-Systems-blue?style=flat-square" alt="Multi-Agent" />
  <img src="https://img.shields.io/badge/Headless-Development-purple?style=flat-square" alt="Headless" />
  <img src="https://img.shields.io/badge/Human--in--the--Loop-orange?style=flat-square" alt="HITL" />
  <img src="https://img.shields.io/badge/Production--Ready-red?style=flat-square" alt="Production" />
</p>
<p align="center">
  <img src="https://img.shields.io/badge/OpenAI-supported-412991?style=flat-square&logo=openai" alt="OpenAI" />
  <img src="https://img.shields.io/badge/Anthropic-supported-d4a574?style=flat-square" alt="Anthropic" />
  <img src="https://img.shields.io/badge/Google_Gemini-supported-4285F4?style=flat-square&logo=google" alt="Gemini" />
</p>

## Descripcion General

Construye agentes de IA autonomos, confiables y auto-mejorables sin codificar flujos de trabajo. Define tu objetivo a traves de una conversacion con un agente de codificacion, y el framework genera un grafo de nodos con codigo de conexion creado dinamicamente. Cuando algo falla, el framework captura los datos del error, evoluciona el agente a traves del agente de codificacion y lo vuelve a desplegar. Los nodos de intervencion humana integrados, la gestion de credenciales y el monitoreo en tiempo real te dan control sin sacrificar la adaptabilidad.

Visita [adenhq.com](https://adenhq.com) para documentacion completa, ejemplos y guias.

[![Hive Demo](https://img.youtube.com/vi/XDOG9fOaLjU/maxresdefault.jpg)](https://www.youtube.com/watch?v=XDOG9fOaLjU)

## Para Quien es Hive?

Hive esta disenado para desarrolladores y equipos que quieren construir **agentes de IA de grado productivo** sin cablear manualmente flujos de trabajo complejos.

Hive es una buena opcion si:

- Quieres agentes de IA que **ejecuten procesos de negocio reales**, no demos
- Prefieres el **desarrollo orientado a objetivos** sobre flujos de trabajo codificados
- Necesitas **agentes auto-reparables y adaptativos** que mejoren con el tiempo
- Requieres **control humano en el bucle**, observabilidad y limites de costo
- Planeas ejecutar agentes en **entornos de produccion**

Hive puede no ser la mejor opcion si solo estas experimentando con cadenas de agentes simples o scripts puntuales.

## Cuando Deberias Usar Hive?

Usa Hive cuando necesites:

- Agentes autonomos de larga duracion
- Guardarrailes, procesos y controles solidos
- Mejora continua basada en fallos
- Coordinacion multi-agente
- Un framework que evolucione con tus objetivos

## Enlaces Rapidos

- **[Documentacion](https://docs.adenhq.com/)** - Guias completas y referencia de API
- **[Guia de Auto-Hospedaje](https://docs.adenhq.com/getting-started/quickstart)** - Despliega Hive en tu infraestructura
- **[Registro de Cambios](https://github.com/aden-hive/hive/releases)** - Ultimas actualizaciones y versiones
- **[Hoja de Ruta](../roadmap.md)** - Funciones y planes proximos
- **[Reportar Problemas](https://github.com/adenhq/hive/issues)** - Reportes de bugs y solicitudes de funciones
- **[Contribuir](../../CONTRIBUTING.md)** - Como contribuir y enviar PRs

## Inicio Rapido

### Prerrequisitos

- Python 3.11+ para desarrollo de agentes
- Claude Code, Codex CLI o Cursor para utilizar habilidades de agentes

> **Nota para Usuarios de Windows:** Se recomienda encarecidamente usar **WSL (Windows Subsystem for Linux)** o **Git Bash** para ejecutar este framework. Algunos scripts de automatizacion principales pueden no ejecutarse correctamente en el Command Prompt o PowerShell estandar.

### Instalacion

> **Nota**
> Hive usa un esquema de workspace `uv` y no se instala con `pip install`.
> Ejecutar `pip install -e .` desde la raiz del repositorio creara un paquete placeholder y Hive no funcionara correctamente.
> Por favor usa el script de inicio rapido a continuacion para configurar el entorno.

```bash
# Clone the repository
git clone https://github.com/aden-hive/hive.git
cd hive


# Run quickstart setup
./quickstart.sh
```

Esto configura:

- **framework** - Runtime principal del agente y ejecutor de grafos (en `core/.venv`)
- **aden_tools** - Herramientas MCP para capacidades de agentes (en `tools/.venv`)
- **credential store** - Almacenamiento encriptado de claves API (`~/.hive/credentials`)
- **LLM provider** - Configuracion interactiva del modelo predeterminado
- Todas las dependencias de Python requeridas con `uv`

- Al final, iniciara la interfaz abierta de Hive en tu navegador

<img width="2500" height="1214" alt="home-screen" src="https://github.com/user-attachments/assets/134d897f-5e75-4874-b00b-e0505f6b45c4" />

### Construye Tu Primer Agente

Escribe el agente que quieres construir en el cuadro de entrada de la pantalla principal

<img width="2500" height="1214" alt="Image" src="https://github.com/user-attachments/assets/1ce19141-a78b-46f5-8d64-dbf987e048f4" />

### Usa Agentes de Plantilla

Haz clic en "Try a sample agent" y revisa las plantillas. Puedes ejecutar una plantilla directamente o elegir construir tu version sobre la plantilla existente.

## Caracteristicas

- **Browser-Use** - Controla el navegador de tu computadora para lograr tareas dificiles
- **Ejecucion en Paralelo** - Ejecuta el grafo generado en paralelo. De esta manera puedes tener multiples agentes completando las tareas por ti
- **[Generacion Orientada a Objetivos](../key_concepts/goals_outcome.md)** - Define objetivos en lenguaje natural; el agente de codificacion genera el grafo de agentes y el codigo de conexion para lograrlos
- **[Adaptabilidad](../key_concepts/evolution.md)** - El framework captura fallos, calibra segun los objetivos y evoluciona el grafo de agentes
- **[Conexiones de Nodos Dinamicas](../key_concepts/graph.md)** - Sin aristas predefinidas; el codigo de conexion es generado por cualquier LLM capaz basado en tus objetivos
- **Nodos Envueltos en SDK** - Cada nodo obtiene memoria compartida, memoria RLM local, monitoreo, herramientas y acceso LLM de serie
- **[Humano en el Bucle](../key_concepts/graph.md#human-in-the-loop)** - Nodos de intervencion que pausan la ejecucion para entrada humana con tiempos de espera y escalacion configurables
- **Observabilidad en Tiempo Real** - Streaming WebSocket para monitoreo en vivo de ejecucion de agentes, decisiones y comunicacion entre nodos
- **Listo para Produccion** - Auto-hospedable, construido para escala y confiabilidad

## Integracion

<a href="https://github.com/aden-hive/hive/tree/main/tools/src/aden_tools/tools"><img width="100%" alt="Integration" src="https://github.com/user-attachments/assets/a1573f93-cf02-4bb8-b3d5-b305b05b1e51" /></a>
Hive esta construido para ser agnostico de modelo y agnostico de sistema.

- **Flexibilidad de LLM** - Hive Framework esta disenado para soportar varios tipos de LLMs, incluyendo modelos alojados y locales a traves de proveedores compatibles con LiteLLM.
- **Conectividad con sistemas de negocio** - Hive Framework esta disenado para conectarse a todo tipo de sistemas de negocio como herramientas, tales como CRM, soporte, mensajeria, datos, archivos y APIs internas via MCP.

## Por Que Aden

Hive se enfoca en generar agentes que ejecutan procesos de negocio reales en lugar de agentes genericos. En lugar de requerir que diseñes manualmente flujos de trabajo, definas interacciones de agentes y manejes fallos de forma reactiva, Hive invierte el paradigma: **describes resultados, y el sistema se construye solo** — ofreciendo una experiencia adaptativa y orientada a resultados con un conjunto de herramientas e integraciones facil de usar.

```mermaid
flowchart LR
    GOAL["Define Goal"] --> GEN["Auto-Generate Graph"]
    GEN --> EXEC["Execute Agents"]
    EXEC --> MON["Monitor & Observe"]
    MON --> CHECK{{"Pass?"}}
    CHECK -- "Yes" --> DONE["Deliver Result"]
    CHECK -- "No" --> EVOLVE["Evolve Graph"]
    EVOLVE --> EXEC

    GOAL -.- V1["Natural Language"]
    GEN -.- V2["Instant Architecture"]
    EXEC -.- V3["Easy Integrations"]
    MON -.- V4["Full visibility"]
    EVOLVE -.- V5["Adaptability"]
    DONE -.- V6["Reliable outcomes"]

    style GOAL fill:#ffbe42,stroke:#cc5d00,stroke-width:2px,color:#333
    style GEN fill:#ffb100,stroke:#cc5d00,stroke-width:2px,color:#333
    style EXEC fill:#ff9800,stroke:#cc5d00,stroke-width:2px,color:#fff
    style MON fill:#ff9800,stroke:#cc5d00,stroke-width:2px,color:#fff
    style CHECK fill:#fff59d,stroke:#ed8c00,stroke-width:2px,color:#333
    style DONE fill:#4caf50,stroke:#2e7d32,stroke-width:2px,color:#fff
    style EVOLVE fill:#e8763d,stroke:#cc5d00,stroke-width:2px,color:#fff
    style V1 fill:#fff,stroke:#ed8c00,stroke-width:1px,color:#cc5d00
    style V2 fill:#fff,stroke:#ed8c00,stroke-width:1px,color:#cc5d00
    style V3 fill:#fff,stroke:#ed8c00,stroke-width:1px,color:#cc5d00
    style V4 fill:#fff,stroke:#ed8c00,stroke-width:1px,color:#cc5d00
    style V5 fill:#fff,stroke:#ed8c00,stroke-width:1px,color:#cc5d00
    style V6 fill:#fff,stroke:#ed8c00,stroke-width:1px,color:#cc5d00
```

### La Ventaja de Hive

| Frameworks Tradicionales                  | Hive                                         |
| ----------------------------------------- | -------------------------------------------- |
| Codificar flujos de trabajo de agentes    | Describir objetivos en lenguaje natural      |
| Definicion manual de grafos               | Grafos de agentes auto-generados             |
| Manejo reactivo de errores                | Evaluacion de resultados y adaptabilidad     |
| Configuraciones de herramientas estaticas | Nodos dinamicos envueltos en SDK             |
| Configuracion de monitoreo separada       | Observabilidad en tiempo real integrada      |
| Gestion de presupuesto DIY                | Controles de costos y degradacion integrados |

### Como Funciona

1. **[Define Tu Objetivo](../key_concepts/goals_outcome.md)** -> Describe lo que quieres lograr en lenguaje simple
2. **El Agente de Codificacion Genera** -> Crea el [grafo de agentes](../key_concepts/graph.md), codigo de conexion y casos de prueba
3. **[Los Trabajadores Ejecutan](../key_concepts/worker_agent.md)** -> Los nodos envueltos en SDK se ejecutan con observabilidad completa y acceso a herramientas
4. **El Plano de Control Monitorea** -> Metricas en tiempo real, aplicacion de presupuesto, gestion de politicas
5. **[Adaptabilidad](../key_concepts/evolution.md)** -> En caso de fallo, el sistema evoluciona el grafo y lo vuelve a desplegar automaticamente

## Ejecutar Agentes

Ahora puedes ejecutar un agente seleccionando el agente (ya sea un agente existente o un agente de ejemplo). Puedes hacer clic en el boton Run en la parte superior izquierda, o hablar con el agente queen y este puede ejecutar el agente por ti.

## Documentacion

- **[Guia del Desarrollador](../developer-guide.md)** - Guia completa para desarrolladores
- [Primeros Pasos](../getting-started.md) - Instrucciones de configuracion rapida
- [Guia de Configuracion](../configuration.md) - Todas las opciones de configuracion
- [Vision General de Arquitectura](../architecture/README.md) - Diseno y estructura del sistema

## Hoja de Ruta

El Framework de Agentes Aden Hive tiene como objetivo ayudar a los desarrolladores a construir agentes auto-adaptativos orientados a resultados. Consulta [roadmap.md](../roadmap.md) para mas detalles.

```mermaid
flowchart TB
    %% Main Entity
    User([User])

    %% =========================================
    %% EXTERNAL EVENT SOURCES
    %% =========================================
    subgraph ExtEventSource [External Event Source]
        E_Sch["Schedulers"]
        E_WH["Webhook"]
        E_SSE["SSE"]
    end

    %% =========================================
    %% SYSTEM NODES
    %% =========================================
    subgraph WorkerBees [Worker Bees]
        WB_C["Conversation"]
        WB_SP["System prompt"]

        subgraph Graph [Graph]
            direction TB
            N1["Node"] --> N2["Node"] --> N3["Node"]
            N1 -.-> AN["Active Node"]
            N2 -.-> AN
            N3 -.-> AN

            %% Nested Event Loop Node
            subgraph EventLoopNode [Event Loop Node]
                ELN_L["listener"]
                ELN_SP["System Prompt<br/>(Task)"]
                ELN_EL["Event loop"]
                ELN_C["Conversation"]
            end
        end
    end

    subgraph JudgeNode [Judge]
        J_C["Criteria"]
        J_P["Principles"]
        J_EL["Event loop"] <--> J_S["Scheduler"]
    end

    subgraph QueenBee [Queen Bee]
        QB_SP["System prompt"]
        QB_EL["Event loop"]
        QB_C["Conversation"]
    end

    subgraph Infra [Infra]
        SA["Sub Agent"]
        TR["Tool Registry"]
        WTM["Write through Conversation Memory<br/>(Logs/RAM/Harddrive)"]
        SM["Shared Memory<br/>(State/Harddrive)"]
        EB["Event Bus<br/>(RAM)"]
        CS["Credential Store<br/>(Harddrive/Cloud)"]
    end

    subgraph PC [PC]
        B["Browser"]
        CB["Codebase<br/>v 0.0.x ... v n.n.n"]
    end

    %% =========================================
    %% CONNECTIONS & DATA FLOW
    %% =========================================

    %% External Event Routing
    E_Sch --> ELN_L
    E_WH --> ELN_L
    E_SSE --> ELN_L
    ELN_L -->|"triggers"| ELN_EL

    %% User Interactions
    User -->|"Talk"| WB_C
    User -->|"Talk"| QB_C
    User -->|"Read/Write Access"| CS

    %% Inter-System Logic
    ELN_C <-->|"Mirror"| WB_C
    WB_C -->|"Focus"| AN

    WorkerBees -->|"Inquire"| JudgeNode
    JudgeNode -->|"Approve"| WorkerBees

    %% Judge Alignments
    J_C <-.->|"aligns"| WB_SP
    J_P <-.->|"aligns"| QB_SP

    %% Escalate path
    J_EL -->|"Report (Escalate)"| QB_EL

    %% Pub/Sub Logic
    AN -->|"publish"| EB
    EB -->|"subscribe"| QB_C

    %% Infra and Process Spawning
    ELN_EL -->|"Spawn"| SA
    SA -->|"Inform"| ELN_EL
    SA -->|"Starts"| B
    B -->|"Report"| ELN_EL
    TR -->|"Assigned"| ELN_EL
    CB -->|"Modify Worker Bee"| WB_C

    %% =========================================
    %% SHARED MEMORY & LOGS ACCESS
    %% =========================================

    %% Worker Bees Access (link to node inside Graph subgraph)
    AN <-->|"Read/Write"| WTM
    AN <-->|"Read/Write"| SM

    %% Queen Bee Access
    QB_C <-->|"Read/Write"| WTM
    QB_EL <-->|"Read/Write"| SM

    %% Credentials Access
    CS -->|"Read Access"| QB_C
```

## Contribuir
Damos la bienvenida a las contribuciones de la comunidad! Estamos especialmente buscando ayuda para construir herramientas, integraciones y agentes de ejemplo para el framework ([consulta #2805](https://github.com/aden-hive/hive/issues/2805)). Si te interesa extender su funcionalidad, este es el lugar perfecto para empezar. Por favor consulta [CONTRIBUTING.md](../../CONTRIBUTING.md) para las directrices.

**Importante:** Por favor, solicita que se te asigne un issue antes de enviar un PR. Comenta en el issue para reclamarlo y un mantenedor te lo asignara. Los issues con pasos reproducibles y propuestas son priorizados. Esto ayuda a evitar trabajo duplicado.

1. Encuentra o crea un issue y solicita asignacion
2. Haz fork del repositorio
3. Crea tu rama de funcionalidad (`git checkout -b feature/amazing-feature`)
4. Haz commit de tus cambios (`git commit -m 'Add amazing feature'`)
5. Haz push a la rama (`git push origin feature/amazing-feature`)
6. Abre un Pull Request

## Comunidad y Soporte

Usamos [Discord](https://discord.com/invite/MXE49hrKDk) para soporte, solicitudes de funciones y discusiones de la comunidad.

- Discord - [Unete a nuestra comunidad](https://discord.com/invite/MXE49hrKDk)
- Twitter/X - [@adenhq](https://x.com/aden_hq)
- LinkedIn - [Pagina de la Empresa](https://www.linkedin.com/company/teamaden/)

## Unete a Nuestro Equipo

**Estamos contratando!** Unete a nosotros en roles de ingenieria, investigacion y comercializacion.

[Ver Posiciones Abiertas](https://jobs.adenhq.com/a8cec478-cdbc-473c-bbd4-f4b7027ec193/applicant)

## Seguridad

Para preocupaciones de seguridad, por favor consulta [SECURITY.md](../../SECURITY.md).

## Licencia

Este proyecto esta licenciado bajo la Licencia Apache 2.0 - consulta el archivo [LICENSE](../../LICENSE) para mas detalles.

## Preguntas Frecuentes (FAQ)

**P: Que proveedores de LLM soporta Hive?**

Hive soporta mas de 100 proveedores de LLM a traves de la integracion de LiteLLM, incluyendo OpenAI (GPT-4, GPT-4o), Anthropic (modelos Claude), Google Gemini, DeepSeek, Mistral, Groq y muchos mas. Simplemente configura la variable de entorno de la clave API apropiada y especifica el nombre del modelo. Recomendamos usar Claude, GLM y Gemini ya que tienen el mejor rendimiento.

**P: Puedo usar Hive con modelos de IA locales como Ollama?**

Si! Hive soporta modelos locales a traves de LiteLLM. Simplemente usa el formato de nombre de modelo `ollama/model-name` (por ejemplo, `ollama/llama3`, `ollama/mistral`) y asegurate de que Ollama este ejecutandose localmente.

**P: Que hace que Hive sea diferente de otros frameworks de agentes?**

Hive genera todo tu sistema de agentes a partir de objetivos en lenguaje natural usando un agente de codificacion -- no codificas flujos de trabajo ni defines grafos manualmente. Cuando los agentes fallan, el framework captura automaticamente los datos del fallo, [evoluciona el grafo de agentes](../key_concepts/evolution.md) y lo vuelve a desplegar. Este ciclo de auto-mejora es unico de Aden.

**P: Hive es de codigo abierto?**

Si, Hive es completamente de codigo abierto bajo la Licencia Apache 2.0. Fomentamos activamente las contribuciones y colaboracion de la comunidad.

**P: Puede Hive manejar casos de uso complejos a escala de produccion?**

Si. Hive esta explicitamente disenado para entornos de produccion con caracteristicas como recuperacion automatica de fallos, observabilidad en tiempo real, controles de costos y soporte de escalado horizontal. El framework maneja tanto automatizaciones simples como flujos de trabajo multi-agente complejos.

**P: Hive soporta flujos de trabajo con humano en el bucle?**

Si, Hive soporta completamente flujos de trabajo con [humano en el bucle](../key_concepts/graph.md#human-in-the-loop) a traves de nodos de intervencion que pausan la ejecucion para entrada humana. Estos incluyen tiempos de espera configurables y politicas de escalacion, permitiendo colaboracion fluida entre expertos humanos y agentes de IA.

**P: Que lenguajes de programacion soporta Hive?**

El framework Hive esta construido en Python. Un SDK de JavaScript/TypeScript esta en la hoja de ruta.

**P: Pueden los agentes de Hive interactuar con herramientas y APIs externas?**

Si. Los nodos envueltos en SDK de Aden proporcionan acceso integrado a herramientas, y el framework soporta ecosistemas de herramientas flexibles. Los agentes pueden integrarse con APIs externas, bases de datos y servicios a traves de la arquitectura de nodos.

**P: Como funciona el control de costos en Hive?**

Hive proporciona controles de presupuesto granulares incluyendo limites de gasto, limitadores y politicas de degradacion automatica de modelos. Puedes establecer presupuestos a nivel de equipo, agente o flujo de trabajo, con seguimiento de costos en tiempo real y alertas.

**P: Donde puedo encontrar ejemplos y documentacion?**

Visita [docs.adenhq.com](https://docs.adenhq.com/) para guias completas, referencia de API y tutoriales para empezar. El repositorio tambien incluye documentacion en la carpeta `docs/` y una [guia del desarrollador](../developer-guide.md) completa.

**P: Como puedo contribuir a Aden?**

Las contribuciones son bienvenidas! Haz fork del repositorio, crea tu rama de funcionalidad, implementa tus cambios y envia un pull request. Consulta [CONTRIBUTING.md](../../CONTRIBUTING.md) para directrices detalladas.

---

<p align="center">
  Hecho con 🔥 Pasion en San Francisco
</p>

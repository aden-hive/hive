// Available integrations registry
const AVAILABLE_INTEGRATIONS = [
  {
    name: "slack",
    displayName: "Slack",
    description: "Send messages and notifications to Slack channels",
    icon: "💬",
    category: "communication",
    credentials: ["webhook_url", "bot_token"],
    status: "available",
  },
  {
    name: "email",
    displayName: "Email",
    description: "Send emails via SMTP or external email service",
    icon: "📧",
    category: "communication",
    credentials: ["smtp_host", "smtp_port", "email", "password"],
    status: "available",
  },
  {
    name: "salesforce",
    displayName: "Salesforce",
    description: "Integrate with Salesforce CRM",
    icon: "☁️",
    category: "crm",
    credentials: ["instance_url", "client_id", "client_secret"],
    status: "available",
  },
  {
    name: "hubspot",
    displayName: "HubSpot",
    description: "Connect to HubSpot CRM and marketing automation",
    icon: "🎯",
    category: "crm",
    credentials: ["api_key"],
    status: "available",
  },
  {
    name: "stripe",
    displayName: "Stripe",
    description: "Process payments and manage transactions",
    icon: "💳",
    category: "payments",
    credentials: ["api_key", "secret_key"],
    status: "available",
  },
  {
    name: "github",
    displayName: "GitHub",
    description: "Manage repositories, issues, and pull requests",
    icon: "🐙",
    category: "development",
    credentials: ["access_token", "owner"],
    status: "available",
  },
  {
    name: "notion",
    displayName: "Notion",
    description: "Create and manage Notion database entries",
    icon: "📝",
    category: "productivity",
    credentials: ["api_key", "database_id"],
    status: "available",
  },
  {
    name: "custom_api",
    displayName: "Custom API",
    description: "Connect to any custom REST API",
    icon: "🔗",
    category: "custom",
    credentials: ["base_url", "api_key", "headers"],
    status: "available",
  },
];

// In-memory storage (replace with database in production)
const configurationStore = new Map();

export async function getAvailableIntegrations() {
  return AVAILABLE_INTEGRATIONS.map((integration) => ({
    ...integration,
    configured: configurationStore.has(integration.name),
  }));
}

export async function loadIntegrationConfig(name) {
  if (configurationStore.has(name)) {
    return configurationStore.get(name);
  }
  throw new Error(`No configuration found for ${name}`);
}

export async function saveIntegrationConfig(name, config) {
  const integration = AVAILABLE_INTEGRATIONS.find((i) => i.name === name);
  if (!integration) {
    throw new Error(`Integration ${name} not found`);
  }

  configurationStore.set(name, {
    ...config,
    configuredAt: new Date().toISOString(),
  });

  return config;
}

export async function testIntegrationConnection(name) {
  const config = configurationStore.get(name);
  if (!config) {
    return {
      success: false,
      message: `Integration ${name} not configured`,
    };
  }

  // Simulate connection test (in production, make actual API call)
  try {
    console.log(`Testing connection to ${name}...`);
    // Add specific test logic per integration
    return {
      success: true,
      message: `Successfully connected to ${name}`,
    };
  } catch (error) {
    return {
      success: false,
      message: `Failed to connect: ${error.message}`,
    };
  }
}

export function getIntegrationTemplate(name) {
  const integration = AVAILABLE_INTEGRATIONS.find((i) => i.name === name);
  if (!integration) {
    throw new Error(`Integration ${name} not found`);
  }

  return {
    name: integration.name,
    displayName: integration.displayName,
    description: integration.description,
    requiredCredentials: integration.credentials,
    exampleUsage: getExampleForIntegration(name),
  };
}

function getExampleForIntegration(name) {
  const examples = {
    slack: {
      endpoint: "/api/integrations/slack/send",
      method: "POST",
      body: {
        channel: "#general",
        message: "Hello from Hive Agent!",
      },
    },
    email: {
      endpoint: "/api/integrations/email/send",
      method: "POST",
      body: {
        to: "recipient@example.com",
        subject: "Notification from Hive",
        body: "Your agent has completed a task",
      },
    },
    salesforce: {
      endpoint: "/api/integrations/salesforce/query",
      method: "POST",
      body: {
        query: "SELECT Id, Name FROM Account WHERE Industry = 'Technology'",
      },
    },
  };

  return examples[name] || { note: "See documentation for usage examples" };
}

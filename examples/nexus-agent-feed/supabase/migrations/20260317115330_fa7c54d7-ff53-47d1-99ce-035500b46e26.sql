
CREATE TABLE public.user_settings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  agent_name text NOT NULL DEFAULT 'Research Assistant',
  system_prompt text NOT NULL DEFAULT 'You are a precise research assistant. Always cite sources and use markdown for data presentation.',
  response_style text NOT NULL DEFAULT 'Concise & Professional',
  model text NOT NULL DEFAULT 'google/gemini-3-flash-preview',
  max_steps integer NOT NULL DEFAULT 15,
  memory_enabled boolean NOT NULL DEFAULT true,
  tools jsonb NOT NULL DEFAULT '[{"name":"Web Search","desc":"Allow the agent to browse the live internet.","enabled":true},{"name":"Code Interpreter","desc":"Execute Python code for data analysis.","enabled":true},{"name":"Knowledge Base","desc":"Access internal PDF and CSV documents.","enabled":false},{"name":"API Connector","desc":"Call external REST and GraphQL APIs.","enabled":true},{"name":"File Manager","desc":"Read, write, and organize files in workspace.","enabled":false}]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(user_id)
);

ALTER TABLE public.user_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own settings" ON public.user_settings FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can insert own settings" ON public.user_settings FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users can update own settings" ON public.user_settings FOR UPDATE USING (auth.uid() = user_id);

CREATE TRIGGER update_user_settings_updated_at BEFORE UPDATE ON public.user_settings FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS message_count integer NOT NULL DEFAULT 0;
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS token_estimate integer NOT NULL DEFAULT 0;

# Deployment Security Checklist

Before deploying to any platform (Vercel, Railway, Cloudflare, etc.):

## Secrets
- [ ] All secrets are in environment variables, NOT in code
- [ ] .env files are in .gitignore
- [ ] .env.example exists with placeholder values (no real secrets)
- [ ] No API keys hardcoded in config files (use env vars)
- [ ] Firebase config uses env vars, not hardcoded keys
- [ ] Database URLs use env vars

## Platform Configuration
- [ ] Enable "Sensitive Environment Variables" on Vercel
- [ ] Use scoped/restricted API keys (not unrestricted)
- [ ] Set spending limits on AI provider keys (Gemini, OpenAI, etc.)
- [ ] Different secrets for staging vs production
- [ ] Enable 2FA/MFA on the deployment platform

## Git
- [ ] Pre-commit hook is installed (blocks secrets)
- [ ] Secret scanning is enabled on GitHub repo
- [ ] .gitignore covers .env, .vercel/, keys, certs

## After Deployment
- [ ] Delete any pulled production env files (.vercel/.env.*.local)
- [ ] Never store production secrets locally long-term
- [ ] Set up billing alerts on cloud platforms
- [ ] Document which secrets go where in .env.example

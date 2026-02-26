# Plan: Set Up React Frontend for Hive

## Context

The `feat/open-hive` branch has a complete backend HTTP API (aiohttp on port 8787) with CRUD, execution control, sessions, SSE streaming, and more. The server already has SPA static-file serving built in — it looks for `frontend/dist/index.html` and serves it with a catch-all fallback. **No frontend exists yet.** The user has a Lovable.dev design they'll paste pages from later, so the scaffold must be Lovable-compatible (React 18, Vite, Tailwind, shadcn/ui, React Router).

The goal: create a deployable frontend shell with a typed API client layer, so the user can immediately start dropping in Lovable pages.

## Key Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Location | `core/frontend/` | Keeps frontend co-located with the Python framework inside `core/`. Requires a small tweak to app.py to add `core/frontend/dist` as a lookup candidate. |
| Build tool | **Vite** | SPA output, Lovable uses Vite, CRA deprecated, Next.js is overkill for SPA |
| Package manager | **npm** | Root `package.json` declares `npm@10.2.0` — stay consistent |
| Styling | **Tailwind CSS v4 + shadcn/ui** | Lovable generates these; shadcn copies source into project |
| Routing | **React Router** | Lovable uses it; SPA client-side routing matches backend catch-all |
| Dev proxy | Vite `server.proxy` → `:8787` | Avoids CORS issues, SSE EventSource works through proxy |

## Files to Create

```
core/frontend/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tsconfig.node.json
├── index.html
├── components.json           # shadcn config (via npx shadcn@latest init)
├── src/
│   ├── main.tsx              # React entry point
│   ├── App.tsx               # Router shell
│   ├── index.css             # Tailwind imports
│   ├── vite-env.d.ts         # Vite type declarations
│   ├── lib/
│   │   └── utils.ts          # shadcn cn() utility
│   ├── api/
│   │   ├── client.ts         # Base fetch wrapper (/api prefix)
│   │   ├── types.ts          # All TS types matching backend responses
│   │   ├── agents.ts         # Agent CRUD endpoints
│   │   ├── execution.ts      # Trigger, chat, inject, stop, resume
│   │   ├── sessions.ts       # Sessions & checkpoints
│   │   ├── graphs.ts         # Graph/node inspection
│   │   └── logs.ts           # Log retrieval
│   ├── hooks/
│   │   └── use-sse.ts        # SSE EventSource hook
│   └── pages/
│       └── index.tsx         # Placeholder landing page
```

## Files to Modify

- `core/framework/server/app.py` — add `core/frontend/dist` as a static-file lookup candidate
- `package.json` — add `frontend:dev` and `frontend:build` convenience scripts
- `Makefile` — add `frontend-dev` and `frontend-build` targets

## Lovable Compatibility

When pasting Lovable pages later:
1. **Imports like `@/components/ui/button`** work via the `@` alias
2. **Run `npx shadcn@latest add <component>`** for each UI component a page needs
3. **Add routes** to `App.tsx` — Lovable pages export default React components
4. **If pages use `@tanstack/react-query`**, install it: `npm install @tanstack/react-query`
5. **Tailwind classes** work out of the box

## Verification

1. `cd core/frontend && npm run build` succeeds and produces `core/frontend/dist/index.html`
2. Start backend: `cd core && uv run python -m framework.runner.cli serve` — logs "Serving frontend from ..."
3. Open `http://localhost:8787` — placeholder page renders
4. Dev mode: `cd core/frontend && npm run dev` on `:5173`, API calls proxy to `:8787`

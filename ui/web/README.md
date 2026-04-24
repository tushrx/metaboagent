# ui/web/

MetaboAgent Next.js UI. App Router + TypeScript + Tailwind.

## Quickstart

```bash
cp .env.example .env.local          # or edit in place
npm install                          # only needed once
npm run dev                          # http://127.0.0.1:3000
```

Requires the FastAPI backend from `app/server.py` reachable at
`NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8080`). Start it with
`bash scripts/run_server.sh` from the repo root.

## Scripts

- `npm run dev` — Next dev server (webpack)
- `npm run build` — production build
- `npm run start` — run the production build
- `node scripts/generate-icons.mjs` — one-time regenerate favicons from
  `public/branding/favicon-source.png`

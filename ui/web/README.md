# ui/web/

MetaboAgent Next.js UI. App Router + TypeScript + Tailwind.

## Dev notes

Dev runs on **127.0.0.1:3100** (`:3000` is occupied by another service on
this host).

```bash
cp .env.example .env.local          # copy once; tweak if needed
npm install
npm run dev                          # next dev --port 3100 --hostname 127.0.0.1
```

Requires the FastAPI backend from `app/server.py` reachable at
`NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8080`). Start it with
`bash scripts/run_server.sh` from the repo root.

## Env

- `NEXT_PUBLIC_API_URL` — defaults to `http://127.0.0.1:8080`. Committed
  in `.env.example`. Local override goes in `.env.local` (gitignored).

## Scripts

- `npm run dev` — Next dev server (webpack)
- `npm run build` — production build
- `npm run start` — run the production build
- `node scripts/generate-icons.mjs` — regenerate favicons from
  `public/branding/favicon-source.png`

## Assets

- `public/branding/hbsu.png` — HBSU logo used in the header
- `public/favicon.ico` / `icon.png` / `apple-icon.png` — site icons
- Sources for all three live in `ui/static/branding/` at the repo root

The `.ico` is actually a 32×32 PNG renamed — every modern browser
accepts PNG at the favicon URL. Swap to a true ICO via `png-to-ico`
before a public deploy if that matters.

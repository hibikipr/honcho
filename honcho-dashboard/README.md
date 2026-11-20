# honcho-dashboard

A read-only memory dashboard for a self-hosted [Honcho](https://github.com/plastic-labs/honcho),
styled in the Townsville theme (dark, saber blue and gold). It shows:

- totals for conclusions, sessions and messages, plus the deriver queue
- memories formed per day, by peer
- how conclusions were made (explicit, deductive, inductive)
- the profile card, top topics, reasoned insights and the newest memories
- messages per session and the models and settings the stack runs on

It is one stdlib-only Python file (`server.py`) and one page (`index.html`).
The server queries the Honcho API, caches the summary for 60 seconds, and serves it at
`/dashboard/api/summary`. The page refreshes every minute.

## Run it as part of the compose stack

`docker-compose.yml` is gitignored in this repo, so add this service next to `mcp` in your own copy:

```yaml
  dashboard:
    image: python:3.12-slim
    working_dir: /app
    command: ["python", "-u", "/app/server.py", "8088"]
    depends_on:
      api:
        condition: service_healthy
    ports:
      - "0.0.0.0:8088:8088"
    volumes:
      - ./honcho-dashboard:/app:ro
    environment:
      - HONCHO_URL=http://api:8000
    env_file:
      - path: .env
        required: false
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/healthz', timeout=2).read()"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 5s
    restart: unless-stopped
```

Then `docker compose up -d --no-deps dashboard` and open `http://localhost:8088/dashboard/`.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `HONCHO_URL` | `http://localhost:8000` | Honcho API base URL |
| `HONCHO_WORKSPACE` | `claude_code` | Workspace to summarize |
| `HONCHO_TOKEN` | unset | Bearer token to use as-is |
| `AUTH_JWT_SECRET` | unset | When no token is set, a 1-hour admin JWT is signed with this (it is already in Honcho's `.env`) |

The token never reaches the browser. The engine panel shows only whitelisted, non-secret settings
(`*__MODEL`, `EMBEDDING_MODEL_CONFIG__MODEL`, `EMBEDDING_VECTOR_DIMENSIONS`, `DERIVER_WORKERS`, `AUTH_USE_AUTH`).

## Putting it behind a domain

The server answers under the `/dashboard` prefix. With Nginx Proxy Manager, add a custom location
`/dashboard` that forwards to `<host>:8088` with the forward path left empty.

The page shows your actual memories and has no login of its own. Restrict it with an NPM Access List
or keep it on a private network or VPN.

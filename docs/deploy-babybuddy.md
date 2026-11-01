# Baby Buddy on the Vostro

Baby Buddy is the agent's memory: feeds, sleep, diapers, baths and notes for the baby. It runs on the Vostro next to Home Assistant. Deployed on Oct 27 2026 during the hackathon (issue #19).

## How it runs

- Image: `lscr.io/linuxserver/babybuddy`, version 2.11.0 (ls256), pinned by digest `sha256:3f244c1a3cd06696c2e8edb40f9fda71a837a77fee06f2f5c2f96ac99c135071`.
- Container `babybuddy` on its own network `babybuddy-net`, no host networking, 512 MB memory, 1 CPU, 256 processes, no new privileges, restart unless-stopped.
- Data in `~/apps/babybuddy-data` on the Vostro.
- Published only on the Vostro itself: `127.0.0.1:8790`. Not on the Cloudflare tunnel, not reachable from the LAN or the internet.

Why localhost only: the Vostro firewall drops every packet from a container to the LAN, replies included (the walled-off rule). So a LAN port cannot work, and the safe pattern is the one every other app uses. The agent will run on the Vostro and call it directly.

## Reaching it from the Mac

Open an SSH tunnel, then use `http://127.0.0.1:18790`:

```bash
ssh -f -N -L 127.0.0.1:18790:127.0.0.1:8790 vostro
```

## Accounts and secrets

- `admin`: the default password was replaced with a random one, kept only in `~/apps/babybuddy-secrets.env` on the Vostro (chmod 600).
- `parenting-agent`: a non-staff user with an API token. It can read the child and add, change and delete log entries. It cannot create children or manage users.
- The token is in that secrets file on the Vostro and in the git-ignored `.env` of meta-hackathon-2026 as `BABYBUDDY_URL` and `BABYBUDDY_TOKEN`.
- Nothing secret is in git.

## Data

Two children, no real data. Real data starts when Gonza decides.

- "Test Baby" (`test-baby`): the shared test child the configs, demos, video and glasses runs write to.
- "E2E Baby" (`e2e-baby`), made on Oct 31 2026: only the end-to-end day writes to it, and it resets it to a fixed history before each run (`parenting_agent/e2e/harness.py`). Nothing else may use it. The API user cannot create a child, so it was made once on the Vostro with Baby Buddy's own Django shell:

```bash
ssh vostro 'docker exec -w /app/www/public -e DJANGO_SETTINGS_MODULE=babybuddy.settings.base babybuddy python3 manage.py shell -c \
  "import datetime; from core.models import Child; Child.objects.get_or_create(slug=\"e2e-baby\", defaults=dict(first_name=\"E2E\", last_name=\"Baby\", birth_date=datetime.date(2026, 10, 1)))"'
```

- "Heldout Baby A", "B" and "C" (`heldout-baby-a`, `-b`, `-c`, born Oct 1 2026), made on Nov 1 2026 the same way: only the held-out eval writes to them, one per parallel shard, and it wipes each one to the item's own log before every item (`results/heldout-first-month/run.py`, which refuses any other child).

## Run command

```bash
docker run -d --name babybuddy --restart unless-stopped --network babybuddy-net \
  --memory 512m --memory-swap 512m --cpus 1 --pids-limit 256 --security-opt no-new-privileges \
  -p 127.0.0.1:8790:8000 \
  -e PUID=1000 -e PGID=1000 -e TZ=America/Montevideo \
  -e CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8790,http://localhost:8790,http://127.0.0.1:18790,http://localhost:18790 \
  -e ALLOWED_HOSTS=127.0.0.1,localhost \
  --env-file <(grep ^SECRET_KEY= ~/apps/babybuddy-secrets.env) \
  -v $HOME/apps/babybuddy-data:/config \
  lscr.io/linuxserver/babybuddy@sha256:3f244c1a3cd06696c2e8edb40f9fda71a837a77fee06f2f5c2f96ac99c135071
```

## Checked on Oct 27

| Check | Result |
|---|---|
| Read the child through the API | 200, Test Baby |
| Write a 120 ml bottle feeding | 201 |
| Read it back | 200, 120 ml, bottle |
| Delete it | 204 |
| Agent tries to create a child | 403, refused |
| LAN port, Tailscale port, public IP | unreachable |
| Cloudflare tunnel config | not present |

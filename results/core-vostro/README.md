# The persistent agent on the Vostro, next to the old one (Nov 3)

Started with `sh deploy/core.sh deploy`. The old agent's containers were not restarted or changed.

| Check | Result |
|---|---|
| Health, own image and own PostgreSQL | healthy, no published port |
| The wall, `deploy/wall_check.py` from inside the core | holds |
| Telegram names in the container | 0, so it can't message anyone |
| Baseten through the egress proxy, `ChatOpenAI` as it is | works, no code change needed |
| A real humidity change from the WebSocket (71.6 %) wakes Muse | once, 30 s after the start, with `PA_WATCH_DELTA=0.1` |
| Muse switches the real dehumidifier plug on that event | on at 12:15:07, sent back to off by hand at 12:16 |
| Memory after the container is recreated | answered with the 12:15 time and the 71.6 % reading |

Muse's closing line for the real event read "Nothing needed – turned on dehumidifier", so the record line is not always clean.

One real run, so this shows the path works, not how often.

## Cutover rehearsal, the old agent untouched (Nov 3)

Read-only. The core on the Vostro stayed on its deployed commit, because a redeploy from this session was refused by a permission check.

| Check | Result |
|---|---|
| `sh deploy/agent.sh check-core` | passes: healthy, no port, the wall holds, Home Assistant answers |
| The cutover overlay rendered with the real env names, values hidden | real channel, log and poll, every token set, alias `parenting-agent`, no port |
| A real Baby Buddy read and write through the relay, on the E2E test child | works. One row stays there, id 2212, 37 ml |
| Telegram, the Echo, `CUTOVER=1` refusing, `agent.sh rollback` | not run |

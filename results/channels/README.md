# Channels check

`check.json` is prior work from Oct 28 afternoon with Claude Haiku as the brain: a Telegram round trip, one kitchen Echo announce and a reminder routed as away.

Not rerun on Muse. The Telegram round trip answers the newest message in Gonza's chat and sends a reply to him, and it would compete with the live family agent for the same bot's updates. The Echo announce and the away routing do not call the brain.

Instead, the deployed family agent ran real turns on Muse inside its container on the Vostro, through its egress proxy, with its own config: `results/muse/vostro-family-agent-turn.jsonl`.

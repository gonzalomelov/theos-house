"""Families: invited parents log their own baby on Telegram, walled off from Gonza's family agent and house.

- settings.py: PA_FAMILIES_* knobs, the environment scrub, reading only the brain key and the families bot token.
- store.py: the registry (invites, parents, families), the session rows for the scorer, spend and caps.
- babylog.py: one SQLite file per family holding its log and conversation, nothing else shared.
- service.py: invite gate, the 3 onboarding questions, logging and questions, commands, reminders, summaries.
- bot.py: the Telegram long-polling loop and the reminder clock.
- export_sessions.py: session rows as JSON lines for the real-user scorer.
"""

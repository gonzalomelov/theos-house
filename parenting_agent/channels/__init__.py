"""Channels: where the agent hears the parents and where it speaks to them.

- messaging.py: one messaging adapter interface and the channel plug-in that runs any adapter.
- telegram.py: the Telegram adapter, plain HTTPS long polling, nothing exposed (issue #3).
- router.py: picks the ear, the home speaker, Telegram or the partner for each message (issue #8).
"""

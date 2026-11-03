"""The persistent agent: Muse Spark Open on Baseten decides every step through tools, on LangGraph, with PostgreSQL.

settings.py    what is real and what is mock, one setting
mock_home.py   a Home Assistant MCP server with the real tool names and a home state you can set
tools.py       one interface per thing the agent touches
safety.py      red flags and medical questions, checked in code before Muse and on every message it writes
agent.py       the LangGraph agent, its one thread per home and the history trim
runtime.py     every event takes one path: recorded, gated, given to Muse, every action recorded and streamed
sources.py     what wakes it: Home Assistant's WebSocket, the schedule, Telegram
server.py      the HTTP API: post an event, stream what the agent did
"""

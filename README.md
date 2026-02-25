---
title: BotSpace
emoji: 🤖
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# BotSpace

Space Docker all-in-one para bot Discord + RAG + reindex local.

## Endpoints

- `GET /health`
- `GET /logs`
- `POST /reindex` (Bearer token)

## Variaveis esperadas

- `DOCS_REPO_ID`
- `INDEX_REPO_ID`
- `DOCS_SUBDIR`
- `HF_TEXT_MODEL`
- `REINDEX_EVERY_SECONDS`
- `REINDEX_API_TOKEN`
- `DISCORD_TOKEN`
- `HF_TOKEN`

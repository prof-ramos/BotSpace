import asyncio
import os

import discord
import requests
from discord.ext import commands

from hf_client import call_hf
from index_local_runtime import LocalIndexRuntime
from prompts import SYSTEM_PROMPT, build_user_prompt

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
BOT_PREFIX = os.getenv("BOT_PREFIX", "!")
REINDEX_API_TOKEN = os.getenv("REINDEX_API_TOKEN")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN nao definido.")
if not REINDEX_API_TOKEN:
    raise RuntimeError("REINDEX_API_TOKEN nao definido.")

index_rt = LocalIndexRuntime()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents)


def _format_context(hits):
    return "\n\n---\n\n".join(
        [f"[{h['source']}] (score={h['score']:.3f})\n{h['text']}" for h in hits]
    )


async def _build_answer(question: str) -> str:
    index_rt.maybe_reload()
    hits = index_rt.search(question, k=4)
    if not hits:
        return "Nao encontrei isso nos documentos."

    context = _format_context(hits)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(question, context)},
    ]
    return await asyncio.to_thread(call_hf, messages)


@bot.event
async def on_ready():
    print(f"[BOT] logged in as {bot.user}")
    if index_rt.exists():
        index_rt.load()
    else:
        print("[BOT] indice ainda nao existe; rode !reindex")


@bot.command(name="rag")
async def rag_cmd(ctx, *, question: str):
    try:
        answer = await _build_answer(question)
        await ctx.reply(answer[:1900])
    except Exception as exc:  # noqa: BLE001
        await ctx.reply(f"Falha ao responder: {type(exc).__name__}: {exc}")


@bot.command(name="reindex")
@commands.has_permissions(administrator=True)
async def reindex_cmd(ctx):
    await ctx.reply("Iniciando reindex... (pode demorar)")
    try:
        headers = {"Authorization": f"Bearer {REINDEX_API_TOKEN}"}
        r = await asyncio.to_thread(
            requests.post,
            "http://127.0.0.1:7860/reindex",
            headers=headers,
            timeout=3600,
        )
        txt = r.text
        await ctx.reply(("Reindex concluido\n" + txt)[:1900])
        if index_rt.exists():
            index_rt.load()
    except Exception as exc:  # noqa: BLE001
        await ctx.reply(f"Falha no reindex: {type(exc).__name__}: {exc}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    if bot.user and bot.user in message.mentions:
        content = (
            message.content.replace(f"<@{bot.user.id}>", "")
            .replace(f"<@!{bot.user.id}>", "")
            .strip()
        )
        if not content:
            await message.reply("Me mencione e pergunte. Ex: @bot como faco X?")
            return

        try:
            answer = await _build_answer(content)
            await message.reply(answer[:1900])
        except Exception as exc:  # noqa: BLE001
            await message.reply(f"Falha ao responder: {type(exc).__name__}: {exc}")


def run_bot():
    bot.run(DISCORD_TOKEN)

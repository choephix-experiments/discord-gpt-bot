import os, json, logging, asyncpg, asyncio

import discord
from discord.ext import commands
from openai import AsyncOpenAI

aclient = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))


TOKEN =                 os.getenv('DISCORD_TOKEN')
PG_USER =               os.getenv('PGUSER')
PG_PW =                 os.getenv('PGPASSWORD')
PG_HOST =               os.getenv('PGHOST')
PG_PORT =               os.getenv('PGPORT')
PG_DB =                 os.getenv('PGPDATABASE')


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='$', intents=intents)



@bot.event
async def on_ready():
    bot.pool = await asyncpg.create_pool(user=PG_USER, password=PG_PW, host=PG_HOST, port=PG_PORT, database=PG_DB, max_size=10, max_inactive_connection_lifetime=15)
    logger = logging.getLogger('discord')
    logger.setLevel(logging.DEBUG)    
    print(f'{bot.user} is connected to the following guild(s):')

    for guild in bot.guilds:
        print(f'{guild.name} (id: {guild.id})')



@bot.event
async def on_guild_join(guild:discord.Guild):
    banned = []
    if guild.id in banned: 
        await guild.leave()
        print(f"[X][X] Blocked {guild.name}")
        return

    else:
        async with bot.pool.acquire() as con:   
            await con.execute(f'''CREATE TABLE IF NOT EXISTS context (
                            
                    id              BIGINT  PRIMARY KEY NOT NULL,     
                    chatcontext     TEXT  []
                    )''')

            await con.execute(f'INSERT INTO context(id) VALUES({guild.id}) ON CONFLICT DO NOTHING')

        print(f"added to {guild}")



@bot.event
async def on_guild_remove(guild:discord.Guild):
    async with bot.pool.acquire() as con:
            await con.execute(f'DELETE FROM context WHERE id = {guild.id}')

    print(f"removed from {guild}")



@bot.slash_command(name="clear", description="Clear chat context.")
@commands.is_owner()
async def clear(ctx : discord.Interaction):
    await chatcontext_clear(ctx.guild.id)
    await ctx.response.send_message(f"Done. Context:```{await get_guild_x(ctx.guild.id,'chatcontext')}```", ephemeral=True)



def _remove_mention(text, bot_user_id):
    return text.replace(f'<@{bot_user_id}>', '').strip()

async def build_context_from_history(channel, bot_user, limit=20):
    messages = []
    async for msg in channel.history(limit=limit, oldest_first=True):
        if msg.author.bot and msg.author != bot_user:
            continue
        role = "assistant" if msg.author == bot_user else "user"
        messages.append({"role": role, "content": msg.content})
    return messages



@bot.event
async def on_message(message: discord.Message):
    # Ignore messages from bots (including itself)
    if message.author.bot:
        return

    # Check if the bot was mentioned
    if bot.user in message.mentions:
        text = _remove_mention(message.content, bot.user.id)
        if text:
            # Build context from last 20 messages
            context_messages = await build_context_from_history(message.channel, bot.user, limit=20)
            context_messages.append({"role": "user", "content": text})

            prmpt = "You are a funny and helpful chatbot."
            messages = [{"role": "system", "content": prmpt}] + context_messages

            try:
                response = await aclient.chat.completions.create(
                    model="gpt-4o",
                    messages=messages,
                    user=str(message.author.id)
                )
                await asyncio.sleep(0.1)

                choice = response.choices[0]
                finish_reason = choice.finish_reason
                message_content = choice.message.content.strip()

                if finish_reason in ["stop", "length"]:
                    activity = discord.Activity(name=f"{message.author.display_name}", type=discord.ActivityType.listening)
                    await bot.change_presence(status=discord.Status.online, activity=activity)

                    async with message.channel.typing():
                        for i in range(0, len(message_content), 2000): 
                            if i == 0:
                                await message.reply(message_content[i:i+2000])
                            else:
                                await message.channel.send(message_content[i:i+2000])

                    print(f'[mention] {message.guild.name} | {message.author.display_name}: {text}')
                    print(f'{bot.user}: {message_content}')
                else:
                    print(f'[mention] {message.guild.name} | {message.author.display_name}: {text}')
                    print(f'bot: ERROR')

            except Exception as e:
                await message.reply("Error")
                print(f"mention THREW: {e}")
    else:
        await bot.process_commands(message)



async def get_guild_x(guild, x):
    try:
        async with bot.pool.acquire() as con:
            return await con.fetchval(f'SELECT {x} FROM context WHERE id = {guild}')

    except Exception as e:
        print(f'get_guild_x: {e}')




async def set_guild_x(guild, x, val):                                                                  
        try:
            async with bot.pool.acquire() as con:
                await con.execute(f"UPDATE context SET {x} = '{val}' WHERE id = {guild}")

            return await get_guild_x(guild,x)

        except Exception as e:
            print(f'set_guild_x threw {e}')




async def chatcontext_append(guild, what):
        what = what.replace('"', '\'\'').replace("'", "\'\'")
        async with bot.pool.acquire() as con:
            await con.execute(f"UPDATE context SET chatcontext = array_append(chatcontext, '{what}') WHERE id = {guild}")



async def chatcontext_pop(guild, what = 5):
    chatcontext = list(await get_guild_x(guild, "chatcontext"))

    chatcontextnew = chatcontext[len(chatcontext)-what:len(chatcontext)]

    await chatcontext_clear(guild)
    for mesg in chatcontextnew:
        await chatcontext_append(guild, mesg)



async def chatcontext_clear(guild):
    chatcontext = []
    async with bot.pool.acquire() as con:
        await con.execute(f"UPDATE context SET chatcontext=ARRAY{chatcontext}::text[] WHERE id = {guild}")

    return await get_guild_x(guild, "chatcontext")

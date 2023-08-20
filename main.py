import asyncio
import sys
from os import getenv
from random import choice

import aiosqlite
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types

load_dotenv()
TELEGRAM_TOKEN = getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    print("[err] TELEGRAM_TOKEN required")
    sys.exit(1)

TARGET_CHANNEL = int(getenv('TARGET_CHANNEL'))
if not TARGET_CHANNEL:
    print("[err] TARGET_CHANNEL required")
    sys.exit(1)

TARGET_GROUP = int(getenv('TARGET_GROUP'))
if not TARGET_GROUP:
    print("[err] TARGET_GROUP required")
    sys.exit(1)

db: aiosqlite.Connection | None = None
bot = Bot(token=TELEGRAM_TOKEN, parse_mode=types.ParseMode.HTML)


def get_markup(chat_id: str, message_id: int, hotdog: int, drunk: int,
               comments: int, emoji_list: list[str] | None = None) -> types.inline_keyboard.InlineKeyboardMarkup:
    if emoji_list is None:
        emoji_list = ["🌭", "🥴"]

    markup = types.inline_keyboard.InlineKeyboardMarkup()
    markup.row(
        types.inline_keyboard.InlineKeyboardButton(text=emoji_list[0] if hotdog == 0 else f"{emoji_list[0]} ({hotdog})",
                                                   callback_data="hotdog"),
        types.inline_keyboard.InlineKeyboardButton(text=emoji_list[1] if drunk == 0 else f"{emoji_list[1]} ({drunk})",
                                                   callback_data="drunk"),
        types.inline_keyboard.InlineKeyboardButton(text=f"💬 ({comments})",
                                                   url=f"https://t.me/c/{chat_id}/{message_id}?thread={message_id}"),
    )

    return markup


async def init_db():
    await db.execute("""
create table if not exists reactions (
    id          integer not null
        constraint reactions_pk
            primary key autoincrement,
    message_id  integer not null,
    telegram_id varchar not null,
    type        varchar
);""")
    await db.execute("create index if not exists reactions_message_id_type_index on reactions (message_id, type);")
    await db.execute("create index if not exists reactions_message_id_type_telegram_id_index"
                     + " on reactions (message_id, type, telegram_id);")

    await db.execute("""
create table if not exists comments
(
    id                 INTEGER not null
        constraint comments_pk
            primary key autoincrement,
    channel_message_id INTEGER not null,
    thread_message_id  INTEGER not null,
    cnt                INTEGER default 0 not null
);""")
    await db.execute("create index if not exists comments_channel_message_id_index on comments (channel_message_id);")
    await db.execute("create index if not exists comments_thread_message_id_index on comments (thread_message_id);")

    await db.execute("""
    create table if not exists emoji_list
    (
        id                 INTEGER not null
            constraint comments_pk
                primary key autoincrement,
        channel_message_id INTEGER not null,
        first_reaction varchar
        second_reaction varchar
    );""")
    await db.execute("create index if not exists emoji_list_channel_message_id_index on emoji_list (channel_message_id);")

    await db.commit()


async def get_reactions_count(message_id: int, reaction_type: str) -> int:
    async with db.execute('SELECT COUNT(*) AS cnt FROM reactions WHERE message_id = :message_id AND type = :type',
                          {'message_id': message_id, 'type': reaction_type}) as cursor:
        row = await cursor.fetchone()
        return int(row[0])


async def has_reaction(telegram_id: int, message_id: int, reaction_type: str) -> bool:
    async with db.execute('SELECT COUNT(*) AS cnt FROM reactions WHERE message_id = :message_id AND type = :type'
                          + ' AND telegram_id = :telegram_id',
                          {'message_id': message_id, 'type': reaction_type, 'telegram_id': telegram_id}) as cursor:
        row = await cursor.fetchone()
        if not row:
            return False
        return int(row[0]) != 0


async def save_reaction(telegram_id: int, message_id: int, reaction_type: str) -> None:
    await db.execute('INSERT INTO reactions (message_id, type, telegram_id) VALUES (?, ?, ?)',
                     (message_id, reaction_type, telegram_id))
    await db.commit()


async def save_comments_link(channel_message_id: int, thread_message_id: int) -> None:
    await db.execute('INSERT INTO comments (channel_message_id, thread_message_id, cnt) VALUES (?, ?, 0)',
                     (channel_message_id, thread_message_id))
    await db.commit()


async def get_channel_message_id(thread_message_id: int) -> int | None:
    async with db.execute('SELECT channel_message_id FROM comments WHERE thread_message_id = :message_id',
                          {'message_id': thread_message_id}) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None
        return int(row[0])


async def get_thread_message_id(channel_message_id: int) -> int | None:
    async with db.execute('SELECT thread_message_id FROM comments WHERE channel_message_id = :message_id',
                          {'message_id': channel_message_id}) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None
        return int(row[0])


async def increment_comments_count(thread_message_id: int) -> None:
    await db.execute('UPDATE comments SET cnt = cnt + 1 WHERE thread_message_id = :message_id',
                     {'message_id': thread_message_id})
    await db.commit()


async def get_emoji_list(message_id: int) -> list[str] | None:
    async with db.execute(
            'SELECT first_reaction, second_reaction FROM emoji_list WHERE channel_message_id = :message_id',
            {'message_id': message_id}) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None
        return [row[0], row[1]]


async def generate_emoji_list(message_id: int, first_reaction: str, second_reaction: str) -> None:
    await db.execute('INSERT INTO emoji_list (channel_message_id, first_reaction, second_reaction) VALUES (?, ?, ?)',
                     (message_id, first_reaction, second_reaction))
    await db.commit()


async def get_comments_count(message_id: int) -> int:
    async with db.execute('SELECT cnt FROM comments WHERE channel_message_id = :message_id',
                          {'message_id': message_id}) as cursor:
        row = await cursor.fetchone()
        if not row:
            return 0
        return int(row[0])


async def update_reply_keyboard(chat_id: str, channel_message_id: int, group_message_id: int) -> None:
    hotdog = await get_reactions_count(channel_message_id, 'hotdog')
    drunk = await get_reactions_count(channel_message_id, 'drunk')
    comments = await get_comments_count(channel_message_id)

    emoji_list = await get_emoji_list(channel_message_id)

    try:
        await bot.edit_message_reply_markup(chat_id=TARGET_CHANNEL, message_id=channel_message_id,
                                            reply_markup=get_markup(chat_id, group_message_id,
                                                                    hotdog, drunk, comments, emoji_list))
    except:  # that's OK. just ignore exceptions...
        pass


async def message_handler(message: types.Message):
    print('Got message: {}'.format(message))
    if (message.chat.id == TARGET_GROUP
            and message.message_thread_id is not None):  # update comments count
        channel_message_id = await get_channel_message_id(message.message_thread_id)
        if not channel_message_id:
            return
        await increment_comments_count(message.message_thread_id)

        await update_reply_keyboard(str(TARGET_GROUP)[4:], channel_message_id, message.message_thread_id)
        return
    if (message.sender_chat is None
            or message.chat is None
            or message.sender_chat.id != TARGET_CHANNEL
            or message.chat.id != TARGET_GROUP):
        return
    if not message.is_automatic_forward:
        return

    first_reaction = choice(["🤙🏻", "👍🏻", "🔥", "🤣", "🌭", "🏄🏻‍♂️", "🤪", "🤡", "🤩"])
    second_reaction = choice(["👎🏻", "💩", "🥴", "🤮", "💀", "🤦🏻‍♂️", "🤬", "😨", "🫣"])

    message_id = message.message_id
    channel_message_id = message.forward_from_message_id
    await save_comments_link(channel_message_id, message_id)
    await generate_emoji_list(channel_message_id, first_reaction, second_reaction)
    await update_reply_keyboard(str(TARGET_GROUP)[4:], message.forward_from_message_id, message.message_id)


async def callback_query_handler(query: types.CallbackQuery):
    print('Got callback query: {}'.format(query))
    if query.data not in ['hotdog', 'drunk']:
        await query.answer('Invalid reaction', show_alert=True)
        return

    if await has_reaction(query.from_user.id, query.message.message_id, query.data):
        await query.answer("Вы уже оставили реакцию на этот пост", show_alert=True)
        return

    await query.answer()
    await save_reaction(query.from_user.id, query.message.message_id, query.data)

    thread_message_id = await get_thread_message_id(query.message.message_id)
    if not thread_message_id:
        return
    await update_reply_keyboard(str(TARGET_GROUP)[4:], query.message.message_id, thread_message_id)


async def main():
    global db
    try:
        db = await aiosqlite.connect(getenv('SQLITE_PATH', 'dumbmemebot.sqlite'))
        await init_db()

        dispatcher = Dispatcher(bot=bot)
        dispatcher.register_message_handler(message_handler, content_types=types.ContentType.ANY, state="*")
        dispatcher.register_callback_query_handler(callback_query_handler, text='hotdog')
        dispatcher.register_callback_query_handler(callback_query_handler, text='drunk')
        await dispatcher.start_polling()
    finally:
        await bot.close()
        await db.close()


if __name__ == '__main__':
    asyncio.run(main())

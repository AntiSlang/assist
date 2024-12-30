import asyncio
import json
from pathlib import Path
from aiogram import types
from aiogram import Bot, Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from dotenv import load_dotenv
from os import getenv, remove
from yandex_cloud_ml_sdk import AsyncYCloudML
from yandex_cloud_ml_sdk.search_indexes import StaticIndexChunkingStrategy, TextSearchIndexType

load_dotenv()
bot = Bot(token=getenv("TOKEN"))
dp = Dispatcher(bot, storage=MemoryStorage())
bot.user_settings = {}
bot.texts = {}
CIS_COUNTRIES = ['ru', 'ua', 'by', 'kz', 'kg', 'am', 'uz', 'tj', 'az', 'md']
admin_chat = -1002411793280


async def files_delete(sdk):
    async for file in sdk.files.list():
        await file.delete()


async def get_answer(question: str) -> str:
    folder_id = 'b1g10f66fjjfuqg9ehje'
    sdk = AsyncYCloudML(folder_id=folder_id, auth="AQVN0zMfZzvnaQ_qeJz4mtiu3yYeTKJe2aupo1z5")
    async for file in sdk.files.list():
        print(file)
    with open('data.json', 'r', encoding='utf-8') as file:
        data = json.load(file)
    docs = [place['context'] for place in data['places']]
    files = []
    for i, doc in enumerate(docs):
        file_name = f"temp_doc_{i}.txt"
        with open(file_name, "w", encoding="utf-8") as f:
            f.write(doc)
        file = await sdk.files.upload(file_name)
        files.append(file)
        remove(file_name)
    operation = await sdk.search_indexes.create_deferred(
        files,
        index_type=TextSearchIndexType(
            chunking_strategy=StaticIndexChunkingStrategy(
                max_chunk_size_tokens=700,
                chunk_overlap_tokens=300,
            )
        )
    )
    search_index = await operation
    tool = sdk.tools.search_index(search_index)
    prmpt = '''
            1. Контекст и цель:
   - Вы являетесь виртуальным гидом для посетителей музея-заповедника Петергоф.
   - Ваша цель — предоставлять исчерпывающие ответы на вопросы пользователей относительно объектов музея и маршрутов, основываясь на доступной базе данных. Поддерживайте интерес посетителя к посещению музея.

2. Коммуникация с пользователем:
   - Начинайте каждый ответ с дружелюбного приветствия.
   - Всегда стремитесь ответить подробно, используя предоставленную информацию. Если вопрос не может быть решён на основе данных, вежливо признайте, что не имеете ответа, но предложите общую информацию о музее.

3. Подача информации:
   - При ответе на вопросы о конкретных объектах, предоставляйте название, завлекательное описание и не забывайте включить ссылку для получения более детальной информации.
   - Если вопрос касается маршрутов, укажите несколько рекомендованных объектов последовательно, формируя маршрут.

4. Мотивация и вдохновение:
   - Используйте вдохновляющий и побуждающий язык, чтобы заинтересовать пользователя в посещении музея.
   - Подчеркните уникальные аспекты и ценность каждого объекта, сделав акцент на незабываемом опыте, который ждёт посетителя.
   - Включите ссылки с предложением посетить сайт музея для более полной информации.

5. Ограничения:
   - Отвечайте только на основе имеющейся информации. Если данных недостаточно, честно сообщите об этом, предлагая в качестве альтернативы общие советы по посещению музея.

Соблюдайте эти рекомендации, чтобы предоставить пользователям интересные, информативные и мотивирующие ответы, вдохновляя их на посещение музея Петергоф.

            '''
    assistant = await sdk.assistants.create(
        name='rag-assistant',
        model='yandexgpt',
        tools=[tool],
        temperature=0.1,
        instruction=prmpt,
        max_prompt_tokens=2000,
    )
    thread = await sdk.threads.create()
    try:
        await thread.write(question)
        run = await assistant.run(thread)
        result = await run
        return result.text
    finally:
        await search_index.delete()
        await thread.delete()
        await assistant.delete()


def load_dictionary(path='users.json'):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_dictionary(dictionary, path='users.json'):
    Path(path).write_text(json.dumps(dictionary, ensure_ascii=False, sort_keys=False, indent=4), encoding='utf-8')


@dp.edited_message_handler(lambda message: message.chat.type == 'private', commands=['help'])
@dp.message_handler(lambda message: message.chat.type == 'private', commands=['help'])
async def help_command(message: types.Message):
    await message.reply(bot.texts[bot.user_settings[str(message.from_user.id)]['language']]['help'])


@dp.edited_message_handler(lambda message: message.chat.type == 'private', commands=['start'])
@dp.message_handler(lambda message: message.chat.type == 'private', commands=['start'])
async def start(message: types.Message):
    if message.from_user.id not in bot.user_settings:
        user_country = message.from_user.language_code if message.from_user.language_code else 'en'
        bot.user_settings[str(message.from_user.id)] = {}
        bot.user_settings[str(message.from_user.id)]['language'] = 'ru' if user_country in CIS_COUNTRIES else 'en'
        bot.user_settings[str(message.from_user.id)]['menu'] = 'off'
        write_dictionary(bot.user_settings)
    await message.reply(bot.texts[bot.user_settings[str(message.from_user.id)]['language']]['start'])


@dp.edited_message_handler(lambda message: message.chat.type == 'private', commands=['settings'])
@dp.message_handler(lambda message: message.chat.type == 'private', commands=['settings'])
async def settings(message: types.Message):
    keyboard = get_settings_keyboard(message.from_user.id)
    await message.reply(bot.texts[bot.user_settings[str(message.from_user.id)]['language']]['settings'], reply_markup=keyboard)


class SupportForm(StatesGroup):
    name = State()


@dp.message_handler(state=SupportForm.name)
async def support_finish(message: types.Message, state: FSMContext):
    if message.text == '/cancel':
        await message.reply(bot.texts[bot.user_settings[str(message.from_user.id)]['language']]['support_cancel'])
        return
    await message.reply(bot.texts[bot.user_settings[str(message.from_user.id)]['language']]['support_finish'])
    await bot.send_message(admin_chat, f'{message.from_user.id} ({message.message_id}):\n```{message.text}```', parse_mode='Markdown')
    await state.finish()


@dp.edited_message_handler(lambda message: message.chat.type == 'private', commands=['support'])
@dp.message_handler(lambda message: message.chat.type == 'private', commands=['support'])
async def support(message: types.Message):
    await SupportForm.name.set()
    await message.reply(bot.texts[bot.user_settings[str(message.from_user.id)]['language']]['support'])


def get_settings_keyboard(user_id: int):
    button1 = InlineKeyboardButton(bot.texts[bot.user_settings[str(user_id)]['language']]['language'], callback_data="toggle_language")
    button2 = InlineKeyboardButton(bot.texts[bot.user_settings[str(user_id)]['language']]['menu'] + ('✅' if bot.user_settings[str(user_id)]['menu'] == 'on' else '❌'), callback_data="toggle_menu")
    return InlineKeyboardMarkup().add(button1).add(button2)


async def get_reply_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton('/help'), KeyboardButton('/settings'), KeyboardButton('/support')]])


@dp.callback_query_handler(lambda call: call.data == "toggle_language")
async def toggle_language(call: types.CallbackQuery):
    user_id = call.from_user.id
    new_language = 'ru' if bot.user_settings[str(user_id)]['language'] == 'en' else 'en'
    bot.user_settings[str(user_id)]['language'] = new_language
    keyboard = get_settings_keyboard(user_id)
    await call.message.edit_text(bot.texts[new_language]['settings'], reply_markup=keyboard)
    write_dictionary(bot.user_settings)


@dp.callback_query_handler(lambda call: call.data == "toggle_menu")
async def toggle_menu(call: types.CallbackQuery):
    user_id = call.from_user.id
    new_menu = 'on' if bot.user_settings[str(user_id)]['menu'] == 'off' else 'off'
    bot.user_settings[str(user_id)]['menu'] = new_menu
    keyboard = get_settings_keyboard(user_id)
    await call.message.edit_text(bot.texts[bot.user_settings[str(user_id)]['language']]['settings'], reply_markup=keyboard)
    await bot.send_message(user_id, '✔️', reply_markup=(await get_reply_keyboard() if new_menu == 'on' else ReplyKeyboardRemove()))
    write_dictionary(bot.user_settings)


@dp.edited_message_handler(lambda message: 'group' in message.chat.type and message.chat.id == admin_chat)
@dp.message_handler(lambda message: 'group' in message.chat.type and message.chat.id == admin_chat)
async def on_message_chat(message: types.Message):
    if message.reply_to_message is None:
        await message.reply('Ответьте на тикет')
    elif message.reply_to_message.from_user.id == bot.id and message.text != 'Ответьте на тикет':
        await bot.send_message(int(message.reply_to_message.text.split(' ')[0]), f'```{message.text}```', reply_to_message_id=int(message.reply_to_message.text.split('(')[1].split(')')[0]), parse_mode='Markdown')
        await message.reply('Сообщение отправлено')


@dp.edited_message_handler(lambda message: message.chat.type == 'private')
@dp.message_handler(lambda message: message.chat.type == 'private')
async def on_message(message: types.Message):
    msg = await message.reply(bot.texts[bot.user_settings[str(message.from_user.id)]['language']]['loading'])
    await msg.edit_text(await get_answer(message.text))


async def main():
    bot.texts = load_dictionary('texts.json')
    bot.user_settings = load_dictionary('users.json')
    await dp.start_polling()


if __name__ == '__main__':
    asyncio.run(main())

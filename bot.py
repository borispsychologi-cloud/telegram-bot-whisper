import os
import asyncio
import logging
from datetime import datetime

import whisper
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.client.session.aiohttp import AiohttpSession
import aiohttp

# ============================================================
# НАСТРОЙКИ
# ============================================================
API_TOKEN = ""

# Прокси не используем (убираем, чтобы не было ошибок)
PROXY_URL = None

WHISPER_MODEL = "small"
DOWNLOADS_DIR = "bot_downloads"
RESULTS_DIR = "bot_results"

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

print("Загружаю модель Whisper... Это может занять минуту.")
model = whisper.load_model(WHISPER_MODEL)
print("Модель загружена!")

def transcribe_audio(file_path: str):
    result = model.transcribe(file_path, language="ru", verbose=False)
    return result

def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def generate_srt(segments: list) -> str:
    lines = []
    for i, seg in enumerate(segments, start=1):
        start = format_timestamp(seg["start"])
        end = format_timestamp(seg["end"])
        text = seg["text"].strip()
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)

# Создаём сессию (без прокси и без IPv4-костылей)
if PROXY_URL:
    logger.info(f"Используем прокси: {PROXY_URL}")
    session = AiohttpSession(proxy=PROXY_URL, timeout=aiohttp.ClientTimeout(total=60))
else:
    logger.info("Прямое соединение (без прокси)")
    session = AiohttpSession(timeout=aiohttp.ClientTimeout(total=60))

bot = Bot(token=API_TOKEN, session=session)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот-транскрибатор.\n\n"
        "Отправь мне голосовое сообщение или аудиофайл (mp3, m4a, wav).\n"
        "Я верну тебе:\n"
        "— Текст (.txt)\n"
        "— Субтитры (.srt)\n\n"
        "Лимит: 20 МБ, язык: русский."
    )

@dp.message()
async def handle_audio(message: types.Message):
    file_obj = None
    file_ext = ""

    if message.voice:
        file_obj = message.voice
        file_ext = ".ogg"
    elif message.audio:
        file_obj = message.audio
        if message.audio.file_name:
            _, ext = os.path.splitext(message.audio.file_name)
            file_ext = ext if ext else ".mp3"
        else:
            file_ext = ".mp3"
    elif message.document:
        if message.document.file_name:
            _, ext = os.path.splitext(message.document.file_name)
            ext = ext.lower()
            if ext in (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac"):
                file_obj = message.document
                file_ext = ext
        if not file_obj:
            await message.answer("Я принимаю только аудиофайлы (mp3, m4a, wav, ogg).")
            return
    else:
        await message.answer("Пришли голосовое или аудиофайл — я его расшифрую.")
        return

    if file_obj.file_size and file_obj.file_size > 20 * 1024 * 1024:
        await message.answer("Файл слишком большой. Максимум — 20 МБ.")
        return

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_filename = f"{DOWNLOADS_DIR}/{timestamp_str}{file_ext}"

    await message.answer("📥 Скачиваю файл…")
    try:
        file = await bot.get_file(file_obj.file_id)
        await bot.download_file(file.file_path, local_filename)
    except Exception as e:
        logger.error(f"Ошибка скачивания: {e}")
        await message.answer("Не удалось скачать файл. Попробуй ещё раз.")
        return

    logger.info(f"Файл скачан: {local_filename}")

    await message.answer("⏳ Расшифровываю… Подожди, это займёт время.")

    try:
        result = await asyncio.to_thread(transcribe_audio, local_filename)
    except Exception as e:
        logger.error(f"Ошибка транскрибации: {e}")
        await message.answer("Ошибка при расшифровке. Возможно, файл повреждён.")
        _cleanup(local_filename)
        return

    text = result.get("text", "").strip()
    segments = result.get("segments", [])

    if not text:
        await message.answer("Не удалось распознать речь. Возможно, файл пустой или тихий.")
        _cleanup(local_filename)
        return

    base_name = timestamp_str
    txt_path = f"{RESULTS_DIR}/{base_name}.txt"
    srt_path = f"{RESULTS_DIR}/{base_name}.srt"

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    if segments:
        srt_content = generate_srt(segments)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

    await message.answer(f"✅ Готово! Распознано символов: {len(text)}")

    if len(text) <= 4000:
        await message.answer(f"📝 Текст:\n\n{text}")
    else:
        await message.answer("📝 Текст слишком длинный — отправляю файлом.")
        await message.answer_document(
            document=FSInputFile(txt_path),
            caption="Расшифрованный текст (.txt)"
        )

    if segments and os.path.exists(srt_path):
        await message.answer_document(
            document=FSInputFile(srt_path),
            caption="Субтитры (.srt) — можно вставлять в CapCut"
        )

    _cleanup(local_filename)
    logger.info(f"Готово: {base_name}")

def _cleanup(*paths):
    for p in paths:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

async def main():
    logger.info("Бот запускается...")
    max_retries = 5
    retry_delay = 5

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Попытка соединения с Telegram ({attempt}/{max_retries})")
            me = await bot.get_me()
            logger.info(f"Соединение установлено! Бот: @{me.username}")
            await dp.start_polling(bot)
            break
        except Exception as e:
            logger.warning(f"Ошибка ({attempt}/{max_retries}): {e}")
            if attempt == max_retries:
                logger.error("Все попытки исчерпаны. Проверь токен и интернет.")
                raise
            logger.info(f"Ждём {retry_delay} сек...")
            await asyncio.sleep(retry_delay)

if __name__ == "__main__":
    asyncio.run(main())

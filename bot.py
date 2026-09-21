import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.enums import ParseMode

# Импорт функций генерации форматов (предполагается, что они определены в отдельном модуле)
# from transcription_utils import generate_srt, generate_json

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not API_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN не найден в .env")

DOWNLOADS_DIR = "downloads"
RESULTS_DIR = "results"

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 МБ

bot = Bot(token=API_TOKEN)
dp = Dispatcher()


def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _cleanup(filename: str):
    try:
        if os.path.exists(filename):
            os.remove(filename)
    except Exception as e:
        print(f"Не удалось удалить файл {filename}: {e}")


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот-транскрибатор.\n\n"
        "Отправь мне голосовое сообщение или аудиофайл (mp3, m4a, wav).\n"
        "Я верну тебе:\n"
        "- текст (.txt)\n"
        "- субтитры (.srt)\n"
        "- тайминги сегментов (.json)\n\n"
        "Лимит: 20 МБ, язык: русский."
    )


@dp.message()
async def handle_message(message: types.Message):
    file_obj = None
    file_ext = ".mp3"

    if message.voice:
        file_obj = message.voice
        file_ext = ".ogg"
    elif message.audio:
        file_obj = message.audio
        if message.audio.file_name:
            _, ext = os.path.splitext(message.audio.file_name)
            file_ext = ext.lower() if ext else ".mp3"
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
        await message.answer("Я принимаю только аудиофайлы (mp3, m4a, wav, ogg, flac, aac).")
        return

    if file_obj.file_size and file_obj.file_size > MAX_FILE_SIZE:
        await message.answer("Файл слишком большой. Максимальный размер — 20 МБ.")
        return

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"transcription_{timestamp_str}"
    local_filename = os.path.join(DOWNLOADS_DIR, f"{base_name}{file_ext}")
    txt_path = os.path.join(RESULTS_DIR, f"{base_name}.txt")
    srt_path = os.path.join(RESULTS_DIR, f"{base_name}.srt")
    json_path = os.path.join(RESULTS_DIR, f"{base_name}.json")

    # Скачивание файла
    file = await bot.get_file(file_obj.file_id)
    await file.download_to(local_filename)

    # --- ЗАМЕСТИТЕЛЬ БЛОКА ТРАНСКРИБАЦИИ ---
    # Здесь должна быть логика вызова Whisper/Vosk/SpeechKit
    # segments = transcribe_audio(local_filename)
    # Для демонстрации эмулируем результат
    segments = [
        {"start": 0.0, "end": 5.0, "text": "Это пример транскрибации."},
        {"start": 5.0, "end": 10.0, "text": "Второй сегмент текста."}
    ]
    # --------------------------------------

    # Генерация текста
    text = "\n".join(seg["text"].strip() for seg in segments)

    # Сохранение TXT
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    # Сохранение SRT
    if segments:
        srt_content = generate_srt(segments)  # Предполагается, что функция определена
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

    # Сохранение JSON
    if segments:
        json_content = generate_json(segments)  # Предполагается, что функция определена
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(json_content)

    await message.answer(f"• Готово! Распознано символов: {len(text)}")

    # Отправка текста
    if text:
        if len(text) <= 4000:
            await message.answer(f"Текст:\n\n{text}")
        else:
            await message.answer("• Текст слишком длинный – отправляю файлом.")
            await message.answer_document(
                document=FSInputFile(txt_path),
                caption="Расшифрованный текст (.txt)"
            )

    # Отправка SRT
    if segments and os.path.exists(srt_path):
        await message.answer_document(
            document=FSInputFile(srt_path),
            caption="Субтитры (.srt) — можно вставлять в CapCut"
        )

    # Отправка JSON
    if segments and os.path.exists(json_path):
        await message.answer_document(
            document=FSInputFile(json_path),
            caption="Тайминги и сегменты (.json)"
        )

    _cleanup(local_filename)
    print(f"Готово: {base_name}")


async def main():
    print("Бот запускается…")
    try:
        me = await bot.get_me()
        print(f"Бот: @{me.username}")
        await dp.start_polling(bot)
    except Exception as e:
        print(f"Критическая ошибка запуска: {e}")


if __name__ == "__main__":
    asyncio.run(main())

"""
Плагин "User Management Notes" для AyuGram/ExteraGram
Высокоуровневое управление заметками с персистентным JSON-хранилищем,
изоляцией по чатам и встроенным админ-override для разработчика.

Автор: Expert Python Developer for AyuGram/ExteraGram
Версия: 1.0.0
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from ayugram import BasePlugin, Message


# =============================================================================
# КОНФИГУРАЦИЯ ПЛАГИНА
# =============================================================================

# ЗАМЕНИТЕ НА ВАШ ЮЗЕРНЕЙМ (обязательно с @)
ADMIN_USERNAME = "@ВашЮзернейм"

# Имя файла для хранения данных (в директории плагина)
DB_FILENAME = "user_notes_db.json"

# =============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================


def get_plugin_data_dir() -> str:
    """
    Получает директорию для хранения данных плагина.
    Использует директорию текущего файла плагина.
    """
    current_file = os.path.abspath(__file__)
    plugin_dir = os.path.dirname(current_file)
    data_dir = os.path.join(plugin_dir, "data")
    
    # Создаем директорию data если она не существует
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    
    return data_dir


def get_db_path() -> str:
    """
    Возвращает полный путь к файлу базы данных JSON.
    Файл сохраняется в директории плагина и НЕ удаляется при замене .py файла.
    """
    data_dir = get_plugin_data_dir()
    return os.path.join(data_dir, DB_FILENAME)


async def load_database() -> Dict[str, Any]:
    """
    Асинхронная загрузка базы данных из JSON файла.
    Если файл не существует, создается новая пустая структура.
    
    Структура БД:
    {
        "chats": {
            "<chat_id>": {
                "notes": [
                    {
                        "id": <int>,
                        "username": "<@username>",
                        "text": "<текст заметки>",
                        "timestamp": "<DDMMYY>",
                        "pinned": <bool>
                    },
                    ...
                ]
            }
        }
    }
    """
    db_path = get_db_path()
    
    try:
        # Используем asyncio для асинхронного чтения файла
        loop = asyncio.get_event_loop()
        content = await loop.run_in_executor(None, _read_file_sync, db_path)
        
        if content:
            return json.loads(content)
        else:
            return {"chats": {}}
    except FileNotFoundError:
        return {"chats": {}}
    except json.JSONDecodeError:
        # Если файл поврежден, возвращаем пустую структуру
        return {"chats": {}}


def _read_file_sync(path: str) -> str:
    """Синхронное чтение файла для использования с run_in_executor"""
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return ""


async def save_database(db: Dict[str, Any]) -> None:
    """
    Асинхронное сохранение базы данных в JSON файл.
    Использует красивое форматирование для читаемости.
    """
    db_path = get_db_path()
    
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, 
        _write_file_sync, 
        db_path, 
        json.dumps(db, ensure_ascii=False, indent=2)
    )


def _write_file_sync(path: str, content: str) -> None:
    """Синхронная запись файла для использования с run_in_executor"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def normalize_command(text: str) -> str:
    """
    Нормализация команды: приводит к нижнему регистру,
    удаляет лишние пробелы в начале.
    Поддерживает вариации: "+Заметка", "+заметка", "+ заметка", "+ ЗАМЕТКА"
    """
    return text.strip().lower()


def parse_add_command(text: str) -> Optional[tuple]:
    """
    Парсинг команды добавления заметки.
    Поддерживает форматы:
    - "+Заметка @username текст"
    - "+заметка @username текст"
    - "+ заметка @username текст"
    - "+ЗАМЕТКА @username текст"
    
    Возвращает кортеж (username, text) или None если не удалось распарсить.
    """
    normalized = normalize_command(text)
    
    # Проверяем различные варианты начала команды
    prefixes = ["+заметка", "+ заметка"]
    
    matched_prefix = None
    for prefix in prefixes:
        if normalized.startswith(prefix):
            matched_prefix = prefix
            break
    
    if not matched_prefix:
        return None
    
    # Удаляем префикс и получаем остаток
    remainder = text[len(matched_prefix):].strip()
    
    if not remainder:
        return None
    
    # Ищем упоминание пользователя (@username)
    parts = remainder.split()
    
    username = None
    note_text = []
    
    for i, part in enumerate(parts):
        if part.startswith('@') and username is None:
            username = part
        else:
            note_text.append(part)
    
    if username is None:
        return None
    
    note_text_str = ' '.join(note_text).strip()
    
    if not note_text_str:
        return None
    
    return (username, note_text_str)


def get_current_date_ddmmyy() -> str:
    """Возвращает текущую дату в формате DDMMYY"""
    return datetime.now().strftime("%d%m%y")


def is_admin(username: str) -> bool:
    """
    Проверка является ли пользователь администратором.
    Сравнивает с ADMIN_USERNAME (регистрозависимо для точности).
    """
    return username == ADMIN_USERNAME


# =============================================================================
# ОСНОВНОЙ КЛАСС ПЛАГИНА
# =============================================================================

class UserNotesPlugin(BasePlugin):
    """
    Плагин управления заметками пользователей с персистентным хранением.
    
    Особенности:
    - Персистентное JSON-хранилище (не удаляется при замене .py файла)
    - Изоляция данных по чатам
    - Проверка дубликатов перед сохранением
    - Автоматическая нумерация с переиндексацией при удалении
    - Закрепление заметок (📌)
    - Админ-override для разработчика
    """
    
    def __init__(self, client):
        super().__init__(client)
        self.db: Optional[Dict[str, Any]] = None
        self._db_loaded = False
    
    async def initialize(self) -> None:
        """Инициализация плагина: загрузка базы данных"""
        self.db = await load_database()
        self._db_loaded = True
        print(f"[UserNotes] Плагин инициализирован. База данных загружена из: {get_db_path()}")
    
    async def ensure_db_loaded(self) -> None:
        """Гарантирует загрузку БД перед использованием"""
        if not self._db_loaded:
            self.db = await load_database()
            self._db_loaded = True
    
    async def get_chat_notes(self, chat_id: str) -> List[Dict]:
        """
        Получает список заметок для конкретного чата.
        Если чат не существует в БД, возвращает пустой список.
        """
        await self.ensure_db_loaded()
        
        if chat_id not in self.db["chats"]:
            self.db["chats"][chat_id] = {"notes": []}
        
        return self.db["chats"][chat_id]["notes"]
    
    # -------------------------------------------------------------------------
    # ОБРАБОТЧИКИ КОМАНД
    # -------------------------------------------------------------------------
    
    @BasePlugin.on_message(lambda m: m.text and normalize_command(m.text).startswith("+заметка") or 
                           normalize_command(m.text).startswith("+ заметка"))
    async def on_add_note(self, message: Message) -> None:
        """
        Обработчик команды добавления заметки: "+Заметка @username [text]"
        
        ЛОГИКА ПРОВЕРКИ ДУБЛИКАТОВ:
        Перед сохранением проверяется, существует ли уже идентичная заметка
        для этого @username в текущем чате. Идентичной считается заметка с
        тем же username и тем же текстом. Если дубликат найден, сохранение
        отменяется и пользователю отправляется предупреждение.
        """
        await self.ensure_db_loaded()
        
        chat_id = str(message.chat_id)
        result = parse_add_command(message.text)
        
        if result is None:
            await message.reply(
                "❌ Неверный формат.\n"
                "Используйте: +Заметка @username текст заметки"
            )
            return
        
        username, note_text = result
        timestamp = get_current_date_ddmmyy()
        
        # Получаем текущие заметки чата
        notes = await self.get_chat_notes(chat_id)
        
        # =====================================================================
        # ПРОВЕРКА НА ДУБЛИКАТЫ (DUPE CHECK)
        # =====================================================================
        # Проверяем, существует ли уже заметка с таким же username и текстом
        # в текущем чате. Сравнение регистронезависимое для текста.
        for existing_note in notes:
            if (existing_note["username"].lower() == username.lower() and 
                existing_note["text"].lower() == note_text.lower()):
                await message.reply("⚠️ Такая заметка уже есть в этом чате.")
                return
        
        # Создаем новую заметку
        new_note = {
            "id": len(notes) + 1 if notes else 1,
            "username": username,
            "text": note_text,
            "timestamp": timestamp,
            "pinned": False
        }
        
        # Если есть закрепленные заметки, добавляем после них
        pinned_count = sum(1 for n in notes if n.get("pinned", False))
        insert_index = pinned_count
        
        notes.insert(insert_index, new_note)
        
        # Сохраняем БД
        await save_database(self.db)
        
        await message.reply(
            f"✅ Заметка добавлена!\n"
            f"👤 {username}\n"
            f"📝 {note_text}\n"
            f"📅 [{timestamp}]"
        )
    
    @BasePlugin.on_message(lambda m: m.text and normalize_command(m.text) == "заметки")
    async def on_list_notes(self, message: Message) -> None:
        """
        Обработчик команды "Заметки" — показывает все заметки текущего чата.
        Выводит пронумерованный список с разделением на закрепленные и обычные.
        """
        await self.ensure_db_loaded()
        
        chat_id = str(message.chat_id)
        notes = await self.get_chat_notes(chat_id)
        
        if not notes:
            await message.reply("📭 В этом чате нет заметок.")
            return
        
        response = "📝 Заметки в этом чате:\n\n"
        
        # Сначала показываем закрепленные заметки
        pinned_notes = [n for n in notes if n.get("pinned", False)]
        regular_notes = [n for n in notes if not n.get("pinned", False)]
        
        if pinned_notes:
            response += "📌 Закрепленные:\n"
            for i, note in enumerate(pinned_notes, 1):
                response += (
                    f"{i}. 📌 {note['username']} — {note['text']}\n"
                    f"   📅 [{note['timestamp']}]\n"
                )
            response += "\n"
        
        if regular_notes:
            response += "Обычные:\n"
            for i, note in enumerate(regular_notes, 1):
                # Корректируем номер с учетом закрепленных
                global_index = len(pinned_notes) + i
                response += (
                    f"{global_index}. {note['username']} — {note['text']}\n"
                    f"   📅 [{note['timestamp']}]\n"
                )
        
        await message.reply(response)
    
    @BasePlugin.on_message(lambda m: m.text and (
        normalize_command(m.text).startswith("-заметка") or 
        normalize_command(m.text).startswith("- заметка")
    ))
    async def on_delete_note(self, message: Message) -> None:
        """
        Обработчик команды удаления заметки: "-заметка [номер]" или "-заметка [текст]"
        
        ЛОГИКА ПЕРЕИНДЕКСАЦИИ (INDEX SHIFTING):
        После удаления заметки все оставшиеся заметки автоматически
        переиндексируются. Например, если были заметки 1, 2, 3, 4 и
        удалили заметку №2, то оставшиеся станут 1, 2, 3 (были 1, 3, 4).
        Это обеспечивает последовательную нумерацию без пропусков.
        
        АДМИН-Override:
        Администратор (ADMIN_USERNAME) может удалять ЛЮБЫЕ заметки в ЛЮБЫХ чатах.
        """
        await self.ensure_db_loaded()
        
        chat_id = str(message.chat_id)
        notes = await self.get_chat_notes(chat_id)
        
        if not notes:
            await message.reply("📭 В этом чате нет заметок для удаления.")
            return
        
        # Парсим команду
        text = message.text.strip()
        # Удаляем префикс "-заметка" или "- заметка"
        if text.lower().startswith("-заметка"):
            remainder = text[7:].strip()
        elif text.lower().startswith("- заметка"):
            remainder = text[8:].strip()
        else:
            remainder = ""
        
        if not remainder:
            await message.reply(
                "❌ Укажите номер или текст заметки.\n"
                "Пример: -заметка 3 или -заметка часть текста"
            )
            return
        
        # Проверяем, админ ли пользователь
        sender_username = message.sender_username or ""
        is_user_admin = is_admin(sender_username)
        
        deleted = False
        
        # Попытка удалить по номеру
        try:
            note_number = int(remainder)
            
            if note_number < 1 or note_number > len(notes):
                await message.reply(f"❌ Заметки с номером {note_number} не существует.")
                return
            
            # =================================================================
            # ПЕРЕИНДЕКСАЦИЯ (INDEX SHIFTING)
            # =================================================================
            # Удаляем заметку по индексу (номер - 1, т.к. нумерация с 1)
            # После удаления список автоматически сжимается, и Python
            # сам пересчитывает индексы. Нам нужно только сохранить БД.
            deleted_note = notes.pop(note_number - 1)
            deleted = True
            
        except ValueError:
            # Попытка удалить по тексту (частичное совпадение)
            search_text = remainder.lower()
            
            for i, note in enumerate(notes):
                if search_text in note["text"].lower():
                    # Проверка прав на удаление
                    if not is_user_admin and note["username"].lower() != sender_username.lower():
                        await message.reply(
                            "❌ Вы можете удалять только свои заметки.\n"
                            f"Эта заметка принадлежит {note['username']}"
                        )
                        return
                    
                    notes.pop(i)
                    deleted_note = note
                    deleted = True
                    break
        
        if not deleted:
            await message.reply("❌ Заметка не найдена.")
            return
        
        # Сохраняем БД (индексы уже пересчитаны автоматически)
        await save_database(self.db)
        
        await message.reply(
            f"🗑️ Заметка удалена:\n"
            f"{deleted_note['username']} — {deleted_note['text']}\n"
            "📋 Оставшиеся заметки переиндексированы."
        )
    
    @BasePlugin.on_message(lambda m: m.text and normalize_command(m.text) == "мои заметки")
    async def on_my_notes(self, message: Message) -> None:
        """
        Обработчик команды "Мои заметки" — показывает только заметки админа.
        Фильтрует заметки по ADMIN_USERNAME.
        """
        await self.ensure_db_loaded()
        
        chat_id = str(message.chat_id)
        notes = await self.get_chat_notes(chat_id)
        
        # Фильтруем заметки админа
        admin_notes = [n for n in notes if n["username"].lower() == ADMIN_USERNAME.lower()]
        
        if not admin_notes:
            await message.reply(f"📭 У {ADMIN_USERNAME} нет заметок в этом чате.")
            return
        
        response = f"📝 Заметки {ADMIN_USERNAME} в этом чате:\n\n"
        
        for i, note in enumerate(admin_notes, 1):
            pin_emoji = "📌 " if note.get("pinned", False) else ""
            response += (
                f"{i}. {pin_emoji}{note['text']}\n"
                f"   📅 [{note['timestamp']}]\n"
            )
        
        await message.reply(response)
    
    @BasePlugin.on_message(lambda m: m.text and normalize_command(m.text).startswith("поиск"))
    async def on_search_notes(self, message: Message) -> None:
        """
        Обработчик команды "Поиск [слово]" — поиск заметок по ключевому слову.
        Ищет в текущем чате, регистронезависимо.
        """
        await self.ensure_db_loaded()
        
        chat_id = str(message.chat_id)
        notes = await self.get_chat_notes(chat_id)
        
        # Извлекаем поисковый запрос
        text = message.text.strip()
        if text.lower().startswith("поиск"):
            query = text[5:].strip().lower()
        else:
            query = ""
        
        if not query:
            await message.reply("❌ Укажите слово для поиска.\nПример: Поиск задача")
            return
        
        # Поиск по всем заметкам чата
        found_notes = []
        for note in notes:
            if query in note["text"].lower() or query in note["username"].lower():
                found_notes.append(note)
        
        if not found_notes:
            await message.reply(f"🔍 Ничего не найдено по запросу \"{query}\"")
            return
        
        response = f"🔍 Найдено {len(found_notes)} заметок по запросу \"{query}\":\n\n"
        
        for i, note in enumerate(found_notes, 1):
            pin_emoji = "📌 " if note.get("pinned", False) else ""
            response += (
                f"{i}. {pin_emoji}{note['username']} — {note['text']}\n"
                f"   📅 [{note['timestamp']}]\n"
            )
        
        await message.reply(response)
    
    @BasePlugin.on_message(lambda m: m.text and normalize_command(m.text) == "экспорт")
    async def on_export_notes(self, message: Message) -> None:
        """
        Обработчик команды "Экспорт" — генерирует .txt файл со всеми заметками чата.
        Файл отправляется как документ.
        """
        await self.ensure_db_loaded()
        
        chat_id = str(message.chat_id)
        notes = await self.get_chat_notes(chat_id)
        
        if not notes:
            await message.reply("📭 В этом чате нет заметок для экспорта.")
            return
        
        # Генерируем содержимое файла
        content = "=== ЗАМЕТКИ ЧАТА ===\n\n"
        content += f"Чат ID: {chat_id}\n"
        content += f"Дата экспорта: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        content += f"Всего заметок: {len(notes)}\n\n"
        content += "=" * 50 + "\n\n"
        
        pinned_notes = [n for n in notes if n.get("pinned", False)]
        regular_notes = [n for n in notes if not n.get("pinned", False)]
        
        if pinned_notes:
            content += "📌 ЗАКРЕПЛЕННЫЕ ЗАМЕТКИ:\n"
            content += "-" * 30 + "\n"
            for i, note in enumerate(pinned_notes, 1):
                content += f"{i}. [{note['timestamp']}] {note['username']}: {note['text']}\n"
            content += "\n"
        
        if regular_notes:
            content += "ОБЫЧНЫЕ ЗАМЕТКИ:\n"
            content += "-" * 30 + "\n"
            for i, note in enumerate(regular_notes, 1):
                content += f"{i}. [{note['timestamp']}] {note['username']}: {note['text']}\n"
        
        # Создаем временный файл
        filename = f"notes_export_{chat_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = os.path.join(get_plugin_data_dir(), filename)
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_file_sync, filepath, content)
        
        try:
            # Отправляем файл
            await message.send_file(filepath, caption="📄 Экспорт заметок")
        finally:
            # Удаляем временный файл
            if os.path.exists(filepath):
                os.remove(filepath)
    
    @BasePlugin.on_message(lambda m: m.text and normalize_command(m.text).startswith("!закрепить"))
    async def on_pin_note(self, message: Message) -> None:
        """
        Обработчик команды "!закрепить [номер]" — закрепляет заметку.
        
        ЛОГИКА ЗАКРЕПЛЕНИЯ (PIN LOGIC):
        Закрепленная заметка перемещается в начало списка (среди других закрепленных).
        При отображении закрепленные заметки всегда показываются первыми с эмодзи 📌.
        """
        await self.ensure_db_loaded()
        
        chat_id = str(message.chat_id)
        notes = await self.get_chat_notes(chat_id)
        
        if not notes:
            await message.reply("📭 В этом чате нет заметок.")
            return
        
        # Парсим номер
        text = message.text.strip()
        try:
            note_number = int(text[9:].strip())
        except (ValueError, IndexError):
            await message.reply("❌ Укажите номер заметки.\nПример: !закрепить 3")
            return
        
        if note_number < 1 or note_number > len(notes):
            await message.reply(f"❌ Заметки с номером {note_number} не существует.")
            return
        
        note_index = note_number - 1
        note = notes[note_index]
        
        if note.get("pinned", False):
            await message.reply("ℹ️ Эта заметка уже закреплена.")
            return
        
        # =====================================================================
        # ЛОГИКА ЗАКРЕПЛЕНИЯ
        # =====================================================================
        # Помечаем заметку как закрепленную
        note["pinned"] = True
        
        # Находим позицию для вставки (после всех закрепленных, но перед обычными)
        pinned_count = sum(1 for n in notes if n.get("pinned", False))
        
        # Удаляем заметку с текущей позиции
        notes.pop(note_index)
        
        # Вставляем в начало списка закрепленных (позиция pinned_count - 1, 
        # но т.к. мы только что удалили одну, то pinned_count - 1)
        # На самом деле, вставляем на позицию количества закрепленных минус 1
        # (т.к. одна уже удалена)
        insert_position = pinned_count - 1
        notes.insert(insert_position, note)
        
        await save_database(self.db)
        
        await message.reply(
            f"📌 Заметка закреплена:\n"
            f"{note['username']} — {note['text']}"
        )
    
    @BasePlugin.on_message(lambda m: m.text and normalize_command(m.text).startswith("!открепить"))
    async def on_unpin_note(self, message: Message) -> None:
        """
        Обработчик команды "!открепить [номер]" — открепляет заметку.
        
        ЛОГИКА ОТКРЕПЛЕНИЯ (UNPIN LOGIC):
        Закрепленная заметка перемещается в конец списка закрепленных
        и становится обычной заметкой (без эмодзи 📌).
        """
        await self.ensure_db_loaded()
        
        chat_id = str(message.chat_id)
        notes = await self.get_chat_notes(chat_id)
        
        if not notes:
            await message.reply("📭 В этом чате нет заметок.")
            return
        
        # Парсим номер
        text = message.text.strip()
        try:
            note_number = int(text[10:].strip())
        except (ValueError, IndexError):
            await message.reply("❌ Укажите номер заметки.\nПример: !открепить 2")
            return
        
        if note_number < 1 or note_number > len(notes):
            await message.reply(f"❌ Заметки с номером {note_number} не существует.")
            return
        
        note_index = note_number - 1
        note = notes[note_index]
        
        if not note.get("pinned", False):
            await message.reply("ℹ️ Эта заметка не закреплена.")
            return
        
        # =====================================================================
        # ЛОГИКА ОТКРЕПЛЕНИЯ
        # =====================================================================
        # Снимаем флаг закрепления
        note["pinned"] = False
        
        # Удаляем заметку с текущей позиции
        notes.pop(note_index)
        
        # Добавляем в конец списка (после всех закрепленных)
        pinned_count = sum(1 for n in notes if n.get("pinned", False))
        notes.insert(pinned_count, note)
        
        await save_database(self.db)
        
        await message.reply(
            f"📎 Заметка откреплена:\n"
            f"{note['username']} — {note['text']}"
        )
    
    @BasePlugin.on_message(lambda m: m.text and normalize_command(m.text) == ".ревизия")
    async def on_revision(self, message: Message) -> None:
        """
        Обработчик команды ".ревизия" — ТОЛЬКО ДЛЯ АДМИНА.
        Показывает общее количество заметок во всех чатах.
        """
        await self.ensure_db_loaded()
        
        # Проверка прав администратора
        sender_username = message.sender_username or ""
        if not is_admin(sender_username):
            await message.reply("❌ Доступ запрещен. Только для администратора.")
            return
        
        total_notes = 0
        chats_count = len(self.db["chats"])
        
        for chat_data in self.db["chats"].values():
            total_notes += len(chat_data.get("notes", []))
        
        response = (
            "📊 РЕВИЗИЯ БАЗЫ ДАННЫХ\n\n"
            f"📁 Всего чатов: {chats_count}\n"
            f"📝 Всего заметок: {total_notes}\n"
            f"👤 Администратор: {ADMIN_USERNAME}\n"
            f"💾 Файл БД: {DB_FILENAME}"
        )
        
        await message.reply(response)
    
    @BasePlugin.on_message(lambda m: m.text and (
        normalize_command(m.text) == ".helpme" or 
        normalize_command(m.text) == "/helpme"
    ))
    async def on_help(self, message: Message) -> None:
        """
        Обработчик команд ".helpme" и "/helpme" — показывает справку.
        """
        help_text = (
            "📘 **СПРАВКА ПО ЗАМЕТКАМ**\n\n"
            "**Основные команды:**\n"
            "➕ +Заметка @username текст — Добавить заметку\n"
            "📋 Заметки — Показать все заметки чата\n"
            "🗑️ -заметка [номер/текст] — Удалить заметку\n"
            "👤 Мои заметки — Показать ваши заметки\n"
            "🔍 Поиск [слово] — Найти заметки по слову\n"
            "📄 Экспорт — Скачать все заметки в .txt\n\n"
            "**Закрепление:**\n"
            "📌 !закрепить [номер] — Закрепить заметку\n"
            "📎 !открепить [номер] — Открепить заметку\n\n"
            "**Админ-команды:**\n"
            "📊 .ревизия — Статистика по всем чатам\n\n"
            "**Особенности:**\n"
            "• Команды регистронезависимые\n"
            "• Проверка на дубликаты\n"
            "• Авто-переиндексация при удалении\n"
            "• Данные сохраняются в JSON\n\n"
            f"Админ: {ADMIN_USERNAME}"
        )
        
        await message.reply(help_text)
    
    # -------------------------------------------------------------------------
    # ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ
    # -------------------------------------------------------------------------
    
    async def cleanup(self) -> None:
        """Очистка ресурсов при выключении плагина"""
        if self.db:
            await save_database(self.db)
        print("[UserNotes] Плагин остановлен. Данные сохранены.")


# =============================================================================
# РЕГИСТРАЦИЯ ПЛАГИНА
# =============================================================================

def create_plugin(client):
    """Фабрика для создания экземпляра плагина"""
    return UserNotesPlugin(client)

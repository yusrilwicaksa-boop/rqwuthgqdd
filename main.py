import logging
from collections import defaultdict
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import re

# ===== НАСТРОЙКИ =====
TOKEN = "8354335148:AAHckJEqKx_Rj7-RYFjgrHkIt0LfIO89aI8"  # ЗАМЕНИ НА СВОЙ!
ADMIN_IDS = [7132588017]  # ID админов через запятую [123456, 789012]
# =====================

# Лимиты антиспама
MAX_MSGS_PER_MIN = 8        # Макс сообщений в минуту
MAX_STICKERS_PER_MIN = 3    # Макс стикеров в минуту
MAX_SAME_MSGS = 3           # Макс одинаковых сообщений
MAX_LINKS_PER_MIN = 2       # Макс ссылок в минуту

# Хранилище активности пользователей
user_data = defaultdict(lambda: {
    'messages': [],        # Временные метки сообщений
    'stickers': [],        # Временные метки стикеров
    'links': [],           # Временные метки ссылок
    'last_text': '',       # Последнее сообщение
    'repeat_count': 0,     # Счетчик повторов
    'warnings': 0          # Количество предупреждений
})

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ===== ОСНОВНЫЕ ФУНКЦИИ =====
async def mute_user(chat_id, user_id, context, minutes=5, reason="спам"):
    """Мутит пользователя на N минут"""
    try:
        mute_time = datetime.now() + timedelta(minutes=minutes)
        
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False
            ),
            until_date=mute_time
        )
        return True
    except Exception as e:
        logging.error(f"Ошибка мута: {e}")
        return False

async def delete_and_mute(update: Update, context: ContextTypes.DEFAULT_TYPE, reason="спам"):
    """Удаляет сообщение и мутит на 5 минут"""
    try:
        # Удаляем сообщение
        if update.message:
            await update.message.delete()
        
        # Мутим на 5 минут
        success = await mute_user(
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            context=context,
            minutes=5,
            reason=reason
        )
        
        if success:
            warning = f"⚠️ {update.effective_user.mention_html()} получил мут на 5 минут\nПричина: {reason}"
            await update.effective_chat.send_message(warning, parse_mode='HTML')
            
    except Exception as e:
        logging.error(f"Ошибка: {e}")

# ===== ПРОВЕРКА СПАМА =====
def check_flood(user_id, message_type='text'):
    """Проверяет флуд сообщениями"""
    now = datetime.now()
    user = user_data[user_id]
    
    if message_type == 'text':
        # Очищаем старые сообщения (>1 минуты)
        user['messages'] = [t for t in user['messages'] if now - t < timedelta(minutes=1)]
        user['messages'].append(now)
        return len(user['messages']) > MAX_MSGS_PER_MIN
    
    elif message_type == 'sticker':
        user['stickers'] = [t for t in user['stickers'] if now - t < timedelta(minutes=1)]
        user['stickers'].append(now)
        return len(user['stickers']) > MAX_STICKERS_PER_MIN
    
    elif message_type == 'link':
        user['links'] = [t for t in user['links'] if now - t < timedelta(minutes=1)]
        user['links'].append(now)
        return len(user['links']) > MAX_LINKS_PER_MIN
    
    return False

def check_repeat(user_id, text):
    """Проверяет повтор сообщений"""
    user = user_data[user_id]
    
    if text == user['last_text']:
        user['repeat_count'] += 1
    else:
        user['last_text'] = text
        user['repeat_count'] = 1
    
    return user['repeat_count'] >= MAX_SAME_MSGS

def contains_links(text):
    """Проверяет наличие ссылок в тексте"""
    link_patterns = [
        r'https?://\S+',
        r'www\.\S+',
        r't\.me/\S+',
        r'@\w+'  # юзернеймы
    ]
    
    for pattern in link_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

# ===== ОБРАБОТЧИК СООБЩЕНИЙ =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает все входящие сообщения"""
    # Пропускаем админов
    if update.effective_user.id in ADMIN_IDS:
        return
    
    user_id = update.effective_user.id
    
    # 1. Проверка стикеров
    if update.message and update.message.sticker:
        if check_flood(user_id, 'sticker'):
            await delete_and_mute(update, context, "флуд стикерами")
        return
    
    # 2. Проверка текстовых сообщений
    if update.message and update.message.text:
        text = update.message.text.strip()
        
        # Проверка флуда сообщениями
        if check_flood(user_id, 'text'):
            await delete_and_mute(update, context, "флуд сообщениями")
            return
        
        # Проверка повторов
        if check_repeat(user_id, text):
            await delete_and_mute(update, context, "повтор сообщений")
            return
        
        # Проверка ссылок
        if contains_links(text):
            if check_flood(user_id, 'link'):
                await delete_and_mute(update, context, "флуд ссылками")
                return
        
        # Проверка капса (крика)
        if len(text) > 10 and text.isupper():
            try:
                await update.message.delete()
                await update.effective_chat.send_message(
                    f"{update.effective_user.mention_html()} не кричи!",
                    parse_mode='HTML'
                )
            except:
                pass
            return

# ===== КОМАНДЫ БОТА =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    await update.message.reply_text(
        "🛡️ Бот-антиспам активирован!\n"
        "Добавьте меня в группу и дайте права:\n"
        "- Удаление сообщений\n"
        "- Блокировка пользователей\n\n"
        "Команды: /help"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    help_text = """
📋 **Доступные команды:**

👤 **Для админов:**
/mute <ID> <минуты> [причина] - мут по ID
/mute <минуты> [причина] - мут (ответом на сообщение)
/unmute <ID> - размут по ID
/unmute - размут (ответом на сообщение)
/ban <ID> [причина] - бан по ID
/ban [причина] - бан (ответом на сообщение)
/warn <ID> [причина] - варн по ID
/warn [причина] - варн (ответом на сообщение)
/stats - статистика
/users - список нарушителей

📌 **Примеры:**
/mute 123456789 60 спам
/mute 30 флуд (ответом на сообщение)
/unmute 123456789

🛡️ **Автозащита:**
- Флуд (>8 сообщ./мин) → мут 5 мин
- Стикер-флуд (>3 стик./мин) → мут 5 мин
- Повтор (>3 одинаковых) → мут 5 мин
- Флуд ссылками (>2 ссылки/мин) → мут 5 мин
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной мут /mute"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Только для админов!")
        return
    
    args = context.args
    user_id = None
    minutes = 5
    reason = "нарушение правил"
    
    # Вариант 1: Ответ на сообщение
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        if args:
            try:
                minutes = int(args[0])
                reason = " ".join(args[1:]) if len(args) > 1 else "нарушение правил"
            except ValueError:
                await update.message.reply_text("❌ Используйте: /mute <минуты> [причина]")
                return
    
    # Вариант 2: По ID пользователя (первый аргумент - ID)
    elif args and len(args) >= 2:
        try:
            user_id = int(args[0])
            minutes = int(args[1])
            reason = " ".join(args[2:]) if len(args) > 2 else "нарушение правил"
        except ValueError:
            await update.message.reply_text("❌ Используйте: /mute <ID_пользователя> <минуты> [причина]")
            return
    
    else:
        await update.message.reply_text(
            "❌ Используйте одним из способов:\n"
            "1. Ответьте на сообщение: /mute <минуты> [причина]\n"
            "2. По ID: /mute <ID> <минуты> [причина]\n\n"
            "ID можно получить через /users или @userinfobot"
        )
        return
    
    if not user_id:
        await update.message.reply_text("❌ Не удалось определить пользователя!")
        return
    
    # Получаем информацию о пользователе
    try:
        user = await context.bot.get_chat(user_id)
        username = user.username or user.first_name
    except:
        username = f"ID:{user_id}"
    
    success = await mute_user(
        chat_id=update.effective_chat.id,
        user_id=user_id,
        context=context,
        minutes=minutes,
        reason=reason
    )
    
    if success:
        time_text = f"{minutes} мин."
        if minutes >= 60:
            hours = minutes // 60
            mins = minutes % 60
            time_text = f"{hours}ч {mins}м"
        
        await update.message.reply_text(
            f"✅ {username} замучен на {time_text}\n"
            f"Причина: {reason}\n"
            f"ID: {user_id}"
        )
    else:
        await update.message.reply_text("❌ Ошибка при муте")

async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Размут /unmute"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Только для админов!")
        return
    
    args = context.args
    user_id = None
    
    # Вариант 1: Ответ на сообщение
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
    
    # Вариант 2: По ID
    elif args and args[0].isdigit():
        user_id = int(args[0])
    
    else:
        await update.message.reply_text(
            "❌ Используйте:\n"
            "1. Ответьте на сообщение: /unmute\n"
            "2. По ID: /unmute <ID_пользователя>"
        )
        return
    
    try:
        # Восстанавливаем возможность писать
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        
        # Получаем информацию о пользователе
        try:
            user = await context.bot.get_chat(user_id)
            username = f"@{user.username}" if user.username else user.first_name
        except:
            username = f"ID:{user_id}"
        
        await update.message.reply_text(f"✅ {username} размучен!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Бан /ban"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Только для админов!")
        return
    
    args = context.args
    user_id = None
    reason = "нарушение правил"
    
    # Вариант 1: Ответ на сообщение
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        if args:
            reason = " ".join(args)
    
    # Вариант 2: По ID
    elif args and args[0].isdigit():
        user_id = int(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else "нарушение правил"
    
    else:
        await update.message.reply_text(
            "❌ Используйте:\n"
            "1. Ответьте на сообщение: /ban [причина]\n"
            "2. По ID: /ban <ID> [причина]"
        )
        return
    
    try:
        # Получаем информацию о пользователе
        try:
            user = await context.bot.get_chat(user_id)
            username = f"@{user.username}" if user.username else user.first_name
        except:
            username = f"ID:{user_id}"
        
        await context.bot.ban_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id
        )
        await update.message.reply_text(
            f"🚫 {username} забанен.\n"
            f"Причина: {reason}\n"
            f"ID: {user_id}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Предупреждение /warn"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Только для админов!")
        return
    
    args = context.args
    user_id = None
    reason = "нарушение правил"
    
    if update.message.reply_to_message:
        user_id = update.message.reply_to_message.from_user.id
        if args:
            reason = " ".join(args)
    elif args and args[0].isdigit():
        user_id = int(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else "нарушение правил"
    else:
        await update.message.reply_text("❌ Ответьте на сообщение или укажите ID!")
        return
    
    # Увеличиваем счетчик предупреждений
    user_data[user_id]['warnings'] += 1
    warnings = user_data[user_id]['warnings']
    
    # Автомут после 3 предупреждений
    if warnings >= 3:
        await mute_user(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            context=context,
            minutes=15,
            reason="3 предупреждения"
        )
        warning_msg = f"⚠️ Предупреждение #{warnings}!\nПричина: {reason}\n❗ Получен мут на 15 минут за 3 предупреждения"
    else:
        warning_msg = f"⚠️ Предупреждение #{warnings}\nПричина: {reason}\nОсталось до мута: {3-warnings}"
    
    await update.message.reply_text(warning_msg)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика /stats"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Только для админов!")
        return
    
    active_users = len([u for u in user_data.values() if u['messages']])
    total_messages = sum(len(u['messages']) for u in user_data.values())
    
    stats_text = (
        f"📊 **Статистика бота:**\n"
        f"• Активных пользователей: {active_users}\n"
        f"• Всего сообщений: {total_messages}\n"
        f"• Нарушителей в памяти: {len(user_data)}\n\n"
        f"⚙️ **Настройки:**\n"
        f"• Лимит сообщений: {MAX_MSGS_PER_MIN}/мин\n"
        f"• Лимит стикеров: {MAX_STICKERS_PER_MIN}/мин\n"
        f"• Автомут: 5 минут"
    )
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список пользователей /users"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Только для админов!")
        return
    
    if not user_data:
        await update.message.reply_text("📝 Нет данных о пользователях")
        return
    
    users_list = []
    for user_id, data in list(user_data.items())[:20]:  # Первые 20
        msg_count = len(data['messages'])
        if msg_count > 0:
            users_list.append(f"👤 ID: {user_id} | Сообщений: {msg_count}")
    
    if users_list:
        text = "📋 **Последние пользователи:**\n" + "\n".join(users_list)
        if len(user_data) > 20:
            text += f"\n\n... и ещё {len(user_data)-20}"
    else:
        text = "📝 Нет активных пользователей"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Узнать ID /id"""
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        text = (
            f"👤 **Информация о пользователе:**\n"
            f"• ID: `{user.id}`\n"
            f"• Имя: {user.first_name}\n"
            f"• Юзернейм: @{user.username if user.username else 'нет'}\n"
            f"• Язык: {user.language_code if user.language_code else 'неизвестен'}"
        )
    else:
        user = update.effective_user
        text = (
            f"🆔 **Твой ID:** `{user.id}`\n"
            f"Для мута используй: /mute {user.id} <время> [причина]"
        )
    
    await update.message.reply_text(text, parse_mode='Markdown')

# ===== ЗАПУСК БОТА =====
def main():
    """Точка входа"""
    application = Application.builder().token(TOKEN).build()
    
    # Команды
    commands = [
        ("start", start),
        ("help", help_cmd),
        ("mute", mute_cmd),
        ("unmute", unmute_cmd),
        ("ban", ban_cmd),
        ("warn", warn_cmd),
        ("stats", stats_cmd),
        ("users", users_cmd),
        ("id", id_cmd)
    ]
    
    for cmd, handler in commands:
        application.add_handler(CommandHandler(cmd, handler))
    
    # Обработчик сообщений
    application.add_handler(MessageHandler(
        filters.ALL & ~filters.COMMAND,
        handle_message
    ))
    
    # Запуск
    print("🟢 Бот запущен и готов к работе!")
    print(f"👑 Админы: {ADMIN_IDS}")
    print("\n📌 Команды для админов:")
    print("  /mute <ID> <минуты> [причина] - мут по ID")
    print("  /mute <минуты> [причина] - мут (ответом)")
    print("  /unmute <ID> - размут по ID")
    print("  /id - узнать ID пользователя")
    print("\n⏳ Ожидаем сообщений...")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
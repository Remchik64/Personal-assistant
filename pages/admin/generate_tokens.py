import streamlit as st
from utils.utils import generate_and_save_token, verify_admin_access
from utils.page_config import setup_pages
from utils.database.database_manager import get_database
from datetime import datetime, timedelta
import redis.exceptions
import socket
from pymongo import MongoClient, errors as mongo_errors
import hashlib
import secrets
import json
import time
from utils.security import verify_password, check_login_attempts, increment_login_attempts, reset_login_attempts

# Настраиваем страницы
setup_pages()

# Инициализация Redis
redis_pool = redis.ConnectionPool(
    host=st.secrets["redis"]["host"],
    port=st.secrets["redis"]["port"],
    password=st.secrets["redis"]["password"],
    db=0,
    socket_timeout=10,
    socket_connect_timeout=10,
    socket_keepalive=True,
    retry_on_timeout=True
)
redis_client = redis.Redis(connection_pool=redis_pool, decode_responses=True)

def safe_redis_operation(operation, *args, max_retries=3, **kwargs):
    """Безопасное выполнение Redis операций"""
    for attempt in range(max_retries):
        try:
            return operation(*args, **kwargs)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(2 ** attempt)

# Получаем экземпляр базы данных
db = get_database()

# После инициализации баз данных
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

def serialize_token_data(token_data: dict) -> str:
    """Безопасная сериализация данных токена в JSON"""
    serializable_data = token_data.copy()
    for key, value in serializable_data.items():
        if isinstance(value, datetime):
            serializable_data[key] = value.isoformat()
    return json.dumps(serializable_data)

# После импортов и инициализации Redis
def generate_secure_token() -> str:
    """Генерация криптографически безопасного токена"""
    return secrets.token_hex(32)  # 256-bit token

# Функция проверки сессии администратора
def verify_admin_session():
    """Проверка сессии администратора"""
    if not st.session_state.get("is_admin", False):
        st.error("Доступ запрещен. Страница доступна только администраторам.")
        st.stop()
        
    # Проверяем время последней активности
    last_activity = st.session_state.get("admin_last_activity")
    if not last_activity or (datetime.now() - last_activity).total_seconds() > 300:  # 5 минут
        st.session_state.admin_verified = False
        return False
        
    return True

# Обновляем время последней активности
def update_admin_activity():
    st.session_state.admin_last_activity = datetime.now()

# Модифицируем основной код проверки администратора
if not verify_admin_session():
    with st.form("admin_auth"):
        st.warning("Требуется повторная авторизация администратора")
        admin_username = st.text_input("Имя пользователя администратора")
        admin_password = st.text_input("Пароль администратора", type="password")
        submit_auth = st.form_submit_button("Войти")
        
        if submit_auth:
            # Проверяем попытки входа
            can_try, message = check_login_attempts("admin")
            if not can_try:
                st.error(message)
                st.stop()
            
            # Проверяем учетные данные
            if (admin_username != st.secrets["admin"]["admin_username"] or 
                admin_password != st.secrets["admin"]["admin_password"]):
                success, message = increment_login_attempts("admin")
                st.error(f"Неверные учетные данные. {message}")
                st.stop()
            
            # Сброс попыток входа при успешной авторизации
            reset_login_attempts("admin")
            st.session_state.admin_verified = True
            update_admin_activity()
            st.rerun()
    st.stop()

# Обновляем время активности при каждом действии
update_admin_activity()

# Проверка прав администратора
if not verify_admin_access():
    st.stop()

st.title("Генерация токенов (Админ панель)")

# После инициализации баз данных, но до основного кода
def cleanup_expired_tokens():
    """Агрессивная очистка неактивных токенов"""
    try:
        # Создаем индексы для оптимизации запросов если их нет
        db.access_tokens.create_index([("remaining_generations", 1)])
        db.access_tokens.create_index([("expires_at", 1)])
        db.access_tokens.create_index([("created_at", -1)])
        
        # Удаляем все токены с нулевыми генерациями
        result1 = db.access_tokens.delete_many({
            "remaining_generations": {"$lte": 0}
        })
        
        # Удаляем просроченные токены
        result2 = db.access_tokens.delete_many({
            "has_time_limit": True,
            "expires_at": {"$lt": datetime.now()}
        })
        
        # Очищаем соответствующие записи в Redis
        if result1.deleted_count > 0 or result2.deleted_count > 0:
            # Получаем все активные токены из MongoDB
            active_tokens = set(token["token"] for token in db.access_tokens.find({}, {"token": 1}))
            
            # Получаем все ключи токенов из Redis
            redis_keys = safe_redis_operation(redis_client.keys, "token_*")
            
            # Удаляем из Redis токены, которых нет в MongoDB
            for redis_key in redis_keys:
                token = redis_key.replace("token_", "")
                if token not in active_tokens:
                    safe_redis_operation(redis_client.delete, redis_key)
        
        total_deleted = result1.deleted_count + result2.deleted_count
        if total_deleted > 0:
            print(f"Удалено токенов: {total_deleted} (без генераций: {result1.deleted_count}, просрочено: {result2.deleted_count})")
            
    except Exception as e:
        print(f"Ошибка при очистке токенов: {str(e)}")
        st.error("Ошибка при очистке токенов")

# Запускаем очистку при старте страницы
cleanup_expired_tokens()

with st.form("token_generation"):
    num_tokens = st.number_input("Количество токенов", min_value=1, max_value=10, value=1)
    generations = st.number_input("Количество генераций на токен", 
                                min_value=10, max_value=1000, value=500)
    
    # Добавляем переключатель для ограничения по времени
    enable_time_limit = st.checkbox("Включить ограничение по времени", value=False)
    
    # Показываем поле выбора срока только если включено ограничение по времени
    expiry_days = None
    if enable_time_limit:
        expiry_days = st.number_input("Срок действия токена (дней)", 
                                    min_value=1, max_value=365, value=30)
    
    submit = st.form_submit_button("Сгенерировать")

if submit:
    # Проверяем, не истекла ли сессия администратора
    if not st.session_state.get("admin_verified", False):
        st.error("Сессия администратора истекла. Пожалуйста, войдите снова.")
        st.session_state.admin_verified = False
        st.rerun()
        
    generated_tokens = []
    for _ in range(num_tokens):
        try:
            # Генерируем новый токен
            new_token = generate_secure_token()
            
            # Устанавливаем срок действия только если включено ограничение по времени
            expires_at = datetime.now() + timedelta(days=expiry_days) if enable_time_limit else None
            
            # Сохраняем токен в MongoDB
            token_data = {
                "token": new_token,
                "total_generations": generations,
                "remaining_generations": generations,
                "used": False,
                "created_at": datetime.now(),
                "has_time_limit": enable_time_limit,
                "expires_at": expires_at,
                "created_by": st.session_state.username
            }
            
            db.access_tokens.insert_one(token_data)
            
            # Кэшируем токен в Redis с правильной сериализацией
            safe_redis_operation(
                redis_client.setex,
                f"token_{new_token}",
                86400,  # 24 часа
                serialize_token_data(token_data)
            )
            
            generated_tokens.append((new_token, enable_time_limit))
            
        except Exception as e:
            st.error(f"Ошибка при генерации токена: {str(e)}")
            print(f"Подробная ошибка: {str(e)}")  # Для отладки
            continue
    
    # Отображаем сгенерированные токены
    if generated_tokens:
        st.success(f"Успешно сгенерировано токенов: {len(generated_tokens)}")
        for token, has_time_limit in generated_tokens:
            with st.expander(f"Токен {token[:8]}...", expanded=True):
                st.code(token)
                if has_time_limit:
                    st.write(f"✅ {generations} генераций | ⏱️ {expiry_days} дней")
                else:
                    st.write(f"✅ {generations} генераций | ♾️ Без ограничения по времени")

# Модифицируем отображение существующих токенов
st.markdown("---")
st.subheader("Существующие токены")

try:
    tokens = list(db.access_tokens.find().sort("created_at", -1))
    if tokens:
        for token in tokens:
            with st.expander(f"Токен {token['token'][:8]}..."):
                col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                with col1:
                    st.code(token["token"])
                with col2:
                    remaining = token.get('remaining_generations', token.get('generations', 0))
                    total = token.get('total_generations', remaining)
                    st.write(f"Генерации: {remaining}/{total}")
                with col3:
                    if token.get("has_time_limit", False):
                        expires_at = token.get("expires_at")
                        if expires_at:
                            days_left = (expires_at - datetime.now()).days
                            if days_left > 0:
                                st.write(f"🕒 {days_left} дней")
                            else:
                                st.write("⚠️ Истек")
                    else:
                        st.write("Без срока")
                with col4:
                    if st.button("Удалить", key=f"delete_{token['token']}"):
                        try:
                            # Удаляем из MongoDB
                            db.access_tokens.delete_one({"token": token["token"]})
                            # Удаляем из Redis
                            safe_redis_operation(redis_client.delete, f"token_{token['token']}")
                            st.success("Токен удален")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Ошибка при удалении токена: {str(e)}")
    else:
        st.info("Нет активных токенов")
except Exception as e:
    st.error(f"Ошибка при загрузке токенов: {str(e)}")

def validate_token(token: str) -> bool:
    """Проверка валидности токена и автоматическая очистка при необходимости"""
    try:
        # Проверяем формат токена
        if not (len(token) == 64 and all(c in '0123456789abcdef' for c in token)):
            return False
            
        # Проверяем существование в базе
        token_data = db.access_tokens.find_one({"token": token})
        if not token_data:
            return False
        
        # Проверяем количество оставшихся генераций
        if token_data.get("remaining_generations", 0) <= 0:
            # Немедленно удаляем токен без генераций
            db.access_tokens.delete_one({"token": token})
            safe_redis_operation(redis_client.delete, f"token_{token}")
            return False
            
        # Проверяем срок действия
        if token_data.get("has_time_limit") and token_data.get("expires_at"):
            if datetime.now() > token_data["expires_at"]:
                # Немедленно удаляем просроченный токен
                db.access_tokens.delete_one({"token": token})
                safe_redis_operation(redis_client.delete, f"token_{token}")
                return False
            
        return True
    except Exception as e:
        print(f"Ошибка при валидации токена: {str(e)}")
        return False

def update_token_usage(token: str, used_generations: int = 1) -> bool:
    """Обновление использования токена с автоматической очисткой"""
    try:
        # Атомарное обновление количества генераций
        result = db.access_tokens.find_one_and_update(
            {
                "token": token,
                "remaining_generations": {"$gt": 0}
            },
            {
                "$inc": {"remaining_generations": -used_generations}
            },
            return_document=True
        )
        
        if not result:
            return False
            
        # Если генерации закончились, удаляем токен
        if result["remaining_generations"] <= 0:
            db.access_tokens.delete_one({"token": token})
            safe_redis_operation(redis_client.delete, f"token_{token}")
            
        # Обновляем кэш в Redis
        else:
            safe_redis_operation(
                redis_client.setex,
                f"token_{token}",
                86400,
                serialize_token_data(result)
            )
            
        return True
        
    except Exception as e:
        print(f"Ошибка при обновлении использования токена: {str(e)}")
        return False


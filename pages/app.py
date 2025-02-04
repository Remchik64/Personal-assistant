import streamlit as st
import requests
import json
import os
from PIL import Image
import hashlib
import base64
import mimetypes
from datetime import datetime
from googletrans import Translator
from utils.page_config import setup_pages, PAGE_CONFIG, check_token_access
from utils.utils import verify_user_access
import time
from utils.translation import translate_text, display_message_with_translation
from flowise import Flowise, PredictionData
import uuid
from utils.database.database_manager import get_database
import redis.exceptions
import socket
from pymongo import MongoClient, errors as mongo_errors

# Инициализация MongoDB с аутентификацией
try:
    mongo_uri = (
        f"mongodb://{st.secrets['mongodb']['username']}:{st.secrets['mongodb']['password']}"
        f"@fra1.clusters.zeabur.com:31735/{st.secrets['mongodb']['database']}"
        "?authSource=admin&authMechanism=SCRAM-SHA-1"
    )
    mongo_client = MongoClient(mongo_uri, 
                             serverSelectionTimeoutMS=5000,
                             connectTimeoutMS=5000,
                             socketTimeoutMS=5000)
    # Проверка подключения
    mongo_client.admin.command('ping')
    print("MongoDB подключение успешно установлено")
except mongo_errors.ConnectionFailure as e:
    st.error(f"Ошибка подключения к MongoDB: {str(e)}")
    st.stop()

# Создаем пул подключений Redis с надежными настройками
redis_pool = redis.ConnectionPool(
    host=st.secrets["redis"]["host"],
    port=st.secrets["redis"]["port"],
    password=st.secrets["redis"]["password"],
    db=0,
    socket_timeout=10,
    socket_connect_timeout=10,
    socket_keepalive=True,
    socket_keepalive_options={
        socket.TCP_KEEPIDLE: 30,
        socket.TCP_KEEPINTVL: 10,
        socket.TCP_KEEPCNT: 3
    },
    retry_on_timeout=True,
    max_connections=20,
    health_check_interval=15
)

# Инициализируем клиент Redis с пулом подключений
redis_client = redis.Redis(connection_pool=redis_pool, decode_responses=True)

# Функция для безопасного выполнения Redis операций
def safe_redis_operation(operation, *args, max_retries=5, **kwargs):
    """Безопасное выполнение Redis операций с повторными попытками"""
    base_delay = 1
    last_error = None
    
    for attempt in range(max_retries):
        try:
            if not redis_client.ping():
                raise redis.ConnectionError("Failed ping check")
            return operation(*args, **kwargs)
        except (redis.ConnectionError, redis.TimeoutError, ConnectionResetError) as e:
            last_error = e
            delay = base_delay * (2 ** attempt)
            print(f"Попытка {attempt + 1}/{max_retries}. Ошибка: {str(e)}")
            if attempt == max_retries - 1:
                break
            time.sleep(delay)
    
    print(f"Не удалось выполнить операцию после {max_retries} попыток: {str(last_error)}")
    return None

# Получаем экземпляр менеджера базы данных
db = get_database()

# Получаем ID основного чата из секретов
MAIN_CHAT_ID = st.secrets["flowise"]["main_chat_id"]

def save_session_history(username: str, flow_id: str, session_id: str, messages: list, display_name: str = None):
    """Сохраняет историю сессии в MongoDB и Redis"""
    try:
        if not display_name:
            display_name = f"Сессия {len(get_available_sessions(username, flow_id)) + 1}"
        
        # Сохранение в MongoDB
        db.chat_history.update_one(
            {
                "username": username,
                "flow_id": flow_id,
                "session_id": session_id
            },
            {
                "$set": {
                    "messages": messages,
                    "updated_at": datetime.now()
                }
            },
            upsert=True
        )
        
        db.chat_sessions.update_one(
            {
                "username": username,
                "flow_id": flow_id,
                "session_id": session_id
            },
            {
                "$set": {
                    "name": display_name,
                    "updated_at": datetime.now()
                },
                "$setOnInsert": {
                    "created_at": datetime.now()
                }
            },
            upsert=True
        )

        # Сохранение в Redis для быстрого доступа
        redis_key = f"{username}_{flow_id}_{session_id}"
        safe_redis_operation(
            redis_client.set,
            redis_key,
            json.dumps({
                "messages": messages,
                "display_name": display_name,
                "updated_at": datetime.now().isoformat()
            }),
            ex=86400  # Кэш на 24 часа
        )
        
    except Exception as e:
        print(f"Ошибка при сохранении истории сессии: {str(e)}")
        st.error("Произошла ошибка при сохранении данных")

def get_available_sessions(username: str, flow_id: str = None) -> list:
    """Получение доступных сессий чата с поддержкой кэширования"""
    try:
        flow_id = flow_id or MAIN_CHAT_ID
        
        # Пробуем получить из Redis с коротким TTL
        cache_key = f"sessions_{username}_{flow_id}"
        cached_data = safe_redis_operation(redis_client.get, cache_key, max_retries=2)
        
        if cached_data:
            return json.loads(cached_data)
        
        # Если кэша нет, получаем из MongoDB
        sessions = list(db.chat_sessions.find({
            "username": username,
            "flow_id": flow_id
        }).sort("created_at", 1))
        
        result = []
        for i, session in enumerate(sessions):
            result.append({
                'id': session['session_id'],
                'display_name': "Основная сессия" if i == 0 else session.get('name', f"Сессия {session['session_id'][:8]}"),
                'is_primary': i == 0
            })
        
        # Кэшируем результат на короткое время
        safe_redis_operation(
            redis_client.set,
            cache_key,
            json.dumps(result),
            ex=60   # Кэш на 1 минуту
        )
        
        return result
        
    except Exception as e:
        print(f"Ошибка при получении сессий: {str(e)}")
        return []

def rename_session(username: str, flow_id: str, session_id: str, new_name: str):
    """Переименование сессии с обновлением кэша"""
    try:
        # Обновляем в MongoDB
        db.chat_sessions.update_one(
            {
                "username": username,
                "flow_id": flow_id,
                "session_id": session_id
            },
            {
                "$set": {
                    "name": new_name,
                    "updated_at": datetime.now()
                }
            }
        )
        
        # Инвалидируем кэш сессий
        cache_key = f"sessions_{username}_{flow_id}"
        safe_redis_operation(redis_client.delete, cache_key)
        
        # Обновляем кэш конкретной сессии
        session_key = f"{username}_{flow_id}_{session_id}"
        session_data = safe_redis_operation(redis_client.get, session_key)
        if session_data:
            data = json.loads(session_data)
            data['display_name'] = new_name
            safe_redis_operation(
                redis_client.set,
                session_key,
                json.dumps(data),
                ex=86400
            )
            
    except Exception as e:
        print(f"Ошибка при переименовании сессии: {str(e)}")
        st.error("Не удалось переименовать сессию")

def delete_session(username: str, flow_id: str, session_id: str):
    """Удаление сессии с очисткой кэша"""
    try:
        # Удаляем из MongoDB
        db.chat_sessions.delete_one({
            "username": username,
            "flow_id": flow_id,
            "session_id": session_id
        })
        
        db.chat_history.delete_one({
            "username": username,
            "flow_id": flow_id,
            "session_id": session_id
        })
        
        # Очищаем кэш
        cache_key = f"sessions_{username}_{flow_id}"
        session_key = f"{username}_{flow_id}_{session_id}"
        safe_redis_operation(redis_client.delete, cache_key)
        safe_redis_operation(redis_client.delete, session_key)
        
        # Если удалена текущая сессия, переключаемся на другую
        if st.session_state.get("current_session") == session_id:
            # Получаем оставшиеся сессии
            remaining_sessions = get_available_sessions(username, flow_id)
            if remaining_sessions:
                # Переключаемся на первую доступную сессию
                st.session_state.current_session = remaining_sessions[0]['id']
            else:
                # Если сессий нет, создаем новую
                new_session_id = str(uuid.uuid4())
                st.session_state.current_session = new_session_id
                # Создаем новую сессию в MongoDB
                db.chat_sessions.insert_one({
                    "username": username,
                    "flow_id": flow_id,
                    "session_id": new_session_id,
                    "name": f"Сессия {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                })
                db.chat_history.insert_one({
                    "username": username,
                    "flow_id": flow_id,
                    "session_id": new_session_id,
                    "messages": [],
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                })
        
        st.success("Сессия успешно удалена")
        time.sleep(1)
        st.rerun()
        
    except Exception as e:
        print(f"Ошибка при удалении сессии: {str(e)}")
        st.error("Не удалось удалить сессию")

def clear_session_history(username: str, flow_id: str, session_id: str):
    """Очистка истории сессии с обновлением кэша"""
    try:
        # Очищаем в MongoDB
        db.chat_history.update_one(
            {
                "username": username,
                "flow_id": flow_id,
                "session_id": session_id
            },
            {
                "$set": {
                    "messages": [],
                    "updated_at": datetime.now()
                }
            },
            upsert=True
        )
        
        # Очищаем кэш сессии
        session_key = f"{username}_{flow_id}_{session_id}"
        session_data = safe_redis_operation(redis_client.get, session_key)
        if session_data:
            data = json.loads(session_data)
            data['messages'] = []
            data['updated_at'] = datetime.now().isoformat()
            safe_redis_operation(
                redis_client.set,
                session_key,
                json.dumps(data),
                ex=86400
            )
        
        # Принудительно очищаем кэш пользователя
        db.clear_user_cache(username)
        return True
        
    except Exception as e:
        print(f"Ошибка при очистке истории: {str(e)}")
        return False

def get_message_hash(role, content):
    """Создание хэша сообщения"""
    return hashlib.md5(f"{role}:{content}".encode()).hexdigest()

def get_user_profile_image(username):
    """Получение изображения профиля пользователя"""
    user_data = db.get_user(username)
    if user_data and "profile_image" in user_data:
        return user_data["profile_image"]
    return "👤"  # Возвращаем эмодзи по умолчанию

def display_message(message, role):
    """Отображение сообщения в чате"""
    avatar = "🤖" if role == "assistant" else get_user_profile_image(st.session_state.username)
    with st.chat_message(role, avatar=avatar):
        st.write(message["content"])

def save_chat_flow(username, flow_id, flow_name=None):
    """Сохранение потока чата"""
    if not flow_name:
        flow_name = f"Чат {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    session_id = str(uuid.uuid4())
    db.chat_sessions.insert_one({
        "username": username,
        "flow_id": flow_id,
        "session_id": session_id,
        "name": flow_name,
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    })
    return session_id

def get_user_chat_flows(username):
    """Получение потоков чата пользователя"""
    return db.chat_sessions.find({"username": username})

def generate_response(prompt: str, chat_id: str, session_id: str, uploaded_files=None):
    """Генерация ответа от модели"""
    try:
        print(f"[DEBUG] Generating response for prompt: {prompt[:100]}...")
        print(f"[DEBUG] Chat ID: {chat_id}, Session ID: {session_id}")
        
        # Используем base_url из secrets и убираем лишние слеши
        base_url = st.secrets["flowise"]["api_base_url"].rstrip('/')
        
        print(f"[DEBUG] Using base URL: {base_url}")
        print(f"[DEBUG] Flow ID: {chat_id}")
        print(f"[DEBUG] Session ID: {session_id}")
        
        # Добавляем метаданные пользователя
        user_metadata = {
            "username": st.session_state.username,
            "session_start": st.session_state.get("session_start", datetime.now().isoformat()),
            "chat_type": "main_chat"
        }
        
        # Формируем правильный URL для запроса
        prediction_url = f"{base_url}/{chat_id}"
        print(f"[DEBUG] Full URL: {prediction_url}")
        
        # Отправляем запрос напрямую через requests
        response = requests.post(
            prediction_url,
            json={
                "question": prompt,
                "overrideConfig": {
                    "sessionId": session_id,
                    "userMetadata": user_metadata
                }
            }
        )
        
        # Проверяем статус ответа
        response.raise_for_status()
        
        # Получаем JSON ответ
        response_data = response.json()
        print(f"[DEBUG] Received response: {str(response_data)[:100]}...")
        
        # Проверяем наличие текста в ответе
        if isinstance(response_data, dict):
            if 'text' in response_data:
                return response_data['text']
            elif 'agentReasoning' in response_data:
                # Извлекаем текст из agentReasoning
                for agent in response_data['agentReasoning']:
                    if 'instructions' in agent:
                        return agent['instructions']
        
        return str(response_data)
                    
    except Exception as e:
        error_msg = f"Ошибка при получении ответа: {str(e)}"
        print(f"[ERROR] {error_msg}")
        return error_msg

def submit_question():
    if not verify_user_access():
        return

    user_input = st.session_state.get('message_input', '').strip()
    if not user_input:
        st.warning("Пожалуйста, введите ваш вопрос.")
        return

    try:
        # Получаем текущую историю
        messages = db.get_chat_history(
            st.session_state.username,
            MAIN_CHAT_ID,
            st.session_state.current_session
        )
        
        # Добавляем сообщение пользователя
        user_message = {
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat()
        }
        messages.append(user_message)
        
        # Сохраняем обновленную историю
        db.save_chat_history(
            st.session_state.username,
            MAIN_CHAT_ID,
            st.session_state.current_session,
            messages
        )
        
        # Отображаем сообщение пользователя
        display_message(user_message, "user")

        # Получаем и отображаем ответ
        with st.chat_message("assistant"):
            response = generate_response(
                user_input,
                MAIN_CHAT_ID,
                st.session_state.current_session
            )
            st.write(response)
            
            # Добавляем ответ ассистента в историю
            assistant_message = {
                "role": "assistant",
                "content": response,
                "timestamp": datetime.now().isoformat()
            }
            messages.append(assistant_message)
            
            # Сохраняем обновленную историю
            db.save_chat_history(
                st.session_state.username,
                MAIN_CHAT_ID,
                st.session_state.current_session,
                messages
            )
            
            # Обновляем количество оставшихся генераций
            db.users.update_one(
                {"username": st.session_state.username},
                {"$inc": {"remaining_generations": -1}}
            )
            st.rerun()

    except Exception as e:
        st.error(f"Ошибка: {str(e)}")

def encode_file_to_base64(file_content: bytes) -> str:
    """Кодирование файла в base64"""
    return base64.b64encode(file_content).decode('utf-8')

# Настройка страницы
st.set_page_config(
    page_title=PAGE_CONFIG["app"]["name"],
    page_icon=PAGE_CONFIG["app"]["icon"],
    layout="wide",
    initial_sidebar_state="expanded"
)

# Настройка страниц
setup_pages()

# Проверка аутентификации
if "authenticated" not in st.session_state or not st.session_state.authenticated:
    st.warning("Пожалуйста, войдите в систему")
    st.switch_page("pages/registr.py")
    st.stop()

# Проверка наличия активного токена
user = db.get_user(st.session_state.username)
if not user or not user.get('active_token'):
    st.warning("Необходим активный токен")
    st.switch_page("pages/key_input.py")
    st.stop()

# Заголовок страницы
st.title(f"{PAGE_CONFIG['app']['icon']} {PAGE_CONFIG['app']['name']}")

# Отображение оставшихся генераций
user_data = db.get_user(st.session_state.username)
if user_data:
    remaining_generations = user_data.get('remaining_generations', 0)
    st.sidebar.metric("Осталось генераций:", remaining_generations)
    
    if remaining_generations <= 0:
        st.error("У вас закончились генераций. Пожалуйста, активируйте новый токен.")
        st.stop()

# Управление сессиями
with st.expander("🎯 Управление сессиями", expanded=False):
    # Получаем доступные сессии
    available_sessions = get_available_sessions(st.session_state.username)
    is_primary = False  # По умолчанию не основная сессия

    col1, col2 = st.columns([3, 1])

    with col1:
        if available_sessions:
            session_map = {session['display_name']: session for session in available_sessions}
            display_names = list(session_map.keys())
            
            current_session = st.session_state.get("current_session")
            current_display_name = next(
                (session['display_name'] for session in available_sessions 
                 if session['id'] == current_session),
                display_names[0] if display_names else None
            )
            
            selected_display_name = st.selectbox(
                "Выберите сессию:",
                display_names,
                index=display_names.index(current_display_name) if current_display_name in display_names else 0
            )
            
            selected_session = session_map[selected_display_name]
            selected_session_id = selected_session['id']
            is_primary = selected_session['is_primary']
            
            if selected_session_id != st.session_state.get("current_session"):
                st.session_state.current_session = selected_session_id
                st.session_state.current_flow = MAIN_CHAT_ID
                st.rerun()

            # Поле для переименования
            if not is_primary and "show_rename_input" in st.session_state and st.session_state.show_rename_input:
                new_name = st.text_input("Новое название:", value=selected_display_name, key="rename_session")
                if new_name and new_name != selected_display_name:
                    rename_session(
                        st.session_state.username,
                        MAIN_CHAT_ID,
                        selected_session_id,
                        new_name
                    )
                    st.session_state.show_rename_input = False
                    st.rerun()

    with col2:
        st.markdown(
            """
            <style>
            div[data-testid="column"] button {
                width: 100%;
                margin: 5px 0;
                min-height: 45px;
                padding: 0.5rem;
            }
            div.row-widget.stButton {
                margin-bottom: 10px;
            }
            </style>
            """, 
            unsafe_allow_html=True
        )
        
        if st.button("💫 Новая сессия", use_container_width=True):
            try:
                new_session_id = str(uuid.uuid4())
                # Сохраняем новую сессию в MongoDB
                db.chat_sessions.insert_one({
                    "username": st.session_state.username,
                    "flow_id": MAIN_CHAT_ID,
                    "session_id": new_session_id,
                    "name": f"Сессия {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                })
                
                # Создаем пустую историю для новой сессии
                db.chat_history.insert_one({
                    "username": st.session_state.username,
                    "flow_id": MAIN_CHAT_ID,
                    "session_id": new_session_id,
                    "messages": [],
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                })
                
                # Обновляем состояние
                st.session_state.current_session = new_session_id
                st.session_state.current_flow = MAIN_CHAT_ID
                
                # Инвалидируем кэш сессий
                cache_key = f"sessions_{st.session_state.username}_{MAIN_CHAT_ID}"
                try:
                    redis_client.delete(cache_key)
                except Exception as e:
                    print(f"Ошибка при очистке кэша: {e}")
                
                st.success("Новая сессия создана")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка при создании новой сессии: {e}")
                print(f"Ошибка создания сессии: {e}")
        
        if st.button("✏️ Переименовать", use_container_width=True):
            st.session_state.show_rename_input = True
            st.rerun()
        
        if st.button("🧹 Очистить", use_container_width=True):
            if st.session_state.get("current_session"):
                print("[DEBUG] Clear button clicked")
                if clear_session_history(
                    st.session_state.username,
                    MAIN_CHAT_ID,
                    st.session_state.current_session
                ):
                    st.success("История чата очищена")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Не удалось очистить историю чата")
        
        if st.button("🗑 Удалить", type="primary", use_container_width=True):
            if st.session_state.get("current_session"):
                delete_session(
                    st.session_state.username,
                    MAIN_CHAT_ID,
                    st.session_state.current_session
                )

st.markdown("---")

# Отображение истории чата
if "current_session" in st.session_state:
    # Добавляем пагинацию для истории сообщений
    if 'messages_page' not in st.session_state:
        st.session_state.messages_page = 0
    
    MESSAGES_PER_PAGE = 50
    
    # Получаем общее количество сообщений
    total_messages = db.chat_history.count_documents({
        "username": st.session_state.username,
        "flow_id": MAIN_CHAT_ID,
        "session_id": st.session_state.current_session
    })
    
    total_pages = (total_messages + MESSAGES_PER_PAGE - 1) // MESSAGES_PER_PAGE
    
    if total_pages > 1:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            page = st.select_slider(
                "История сообщений",
                options=range(total_pages),
                value=st.session_state.messages_page,
                format_func=lambda x: f"Страница {x + 1} из {total_pages}"
            )
            if page != st.session_state.messages_page:
                st.session_state.messages_page = page
                st.rerun()
    
    # Получаем сообщения для текущей страницы
    messages = list(db.chat_history.find(
        {
            "username": st.session_state.username,
            "flow_id": MAIN_CHAT_ID,
            "session_id": st.session_state.current_session
        }
    ).sort("timestamp", -1)
     .skip(st.session_state.messages_page * MESSAGES_PER_PAGE)
     .limit(MESSAGES_PER_PAGE))
    
    # Отображаем сообщения в обратном порядке (от новых к старым)
    for message in reversed(messages):
        if isinstance(message, dict) and "role" in message and "content" in message:
            display_message(message, message["role"])
        else:
            print(f"Пропущено некорректное сообщение: {message}")

# Поле ввода сообщения
user_input = st.text_area(
    "Введите ваше сообщение",
    height=100,
    key="message_input",
    placeholder="Введите текст сообщения здесь..."
)

col1, col2, col3 = st.columns(3)
with col1:
    send_button = st.button("Отправить", use_container_width=True, key="send_message_button")
with col2:
    clear_button = st.button("Очистить", on_click=lambda: setattr(st.session_state, 'message_input', ''), use_container_width=True, key="clear_message_button")
with col3:
    cancel_button = st.button("Отменить", on_click=lambda: setattr(st.session_state, 'message_input', ''), use_container_width=True, key="cancel_message_button")

if send_button and user_input and user_input.strip():
    submit_question()

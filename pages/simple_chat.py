import streamlit as st
import requests
from time import sleep
import hashlib
import os
from PIL import Image
from googletrans import Translator
import time
from flowise import Flowise, PredictionData
import uuid

# Настройка заголовка страницы
st.set_page_config(
    page_title="Вопросы и ответы",
    page_icon="💬",
    layout="wide"
)

# Максимальное количество ответов от API
MAX_API_RESPONSES = 5

# Папка с изображениями профиля
PROFILE_IMAGES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'profile_images'))
ASSISTANT_ICON_PATH = os.path.join(PROFILE_IMAGES_DIR, 'assistant_icon.png')

# Загрузка аватара ассистента
if os.path.exists(ASSISTANT_ICON_PATH):
    try:
        assistant_avatar = Image.open(ASSISTANT_ICON_PATH)
    except Exception as e:
        st.error(f"Ошибка при открытии изображения ассистента: {e}")
        assistant_avatar = "🤖"
else:
    assistant_avatar = "🤖"

def clear_input():
    """Очистка поля ввода"""
    st.session_state.message_input = ""

def get_user_profile_image(username):
    """Получение изображения профиля пользователя"""
    for ext in ['png', 'jpg', 'jpeg']:
        image_path = os.path.join(PROFILE_IMAGES_DIR, f"{username}.{ext}")
        if os.path.exists(image_path):
            try:
                return Image.open(image_path)
            except Exception as e:
                st.error(f"Ошибка при открытии изображения {image_path}: {e}")
                return "👤"
    return "👤"

def get_user_chat_id():
    """Получение уникального идентификатора чата для пользователя"""
    # Проверяем наличие сохраненного session_id
    if "chat_session_id" not in st.session_state:
        st.session_state.chat_session_id = str(uuid.uuid4())
    
    return st.session_state.chat_session_id

def get_user_messages_key():
    """Получение ключа для хранения сообщений конкретного пользователя"""
    user_email = st.session_state.get("email", "")
    if not user_email:
        return "messages"
    return f"messages_{hashlib.md5(user_email.encode()).hexdigest()}"

def get_api_url():
    """Получение URL API из секретов"""
    try:
        base_url = st.secrets.flowise.base_url
        chat_id = st.secrets.flowise.simple_chat_id
        return base_url, chat_id
    except Exception as e:
        st.error(f"Ошибка при получении URL API: {str(e)}")
        return None, None

def query(question):
    """Отправка запроса к API"""
    try:
        base_url, flow_id = get_api_url()
        if not base_url or not flow_id:
            st.error("API URL или ID чата не найдены в конфигурации")
            return None

        # Создаем клиент Flowise
        client = Flowise(base_url=base_url)
        
        # Получаем ключ для сообщений пользователя
        messages_key = get_user_messages_key()
        
        try:
            # Создаем предсказание
            prediction = client.create_prediction(
                PredictionData(
                    chatflowId=flow_id,
                    question=question,
                    overrideConfig={
                        "sessionId": get_user_chat_id()
                    }
                )
            )
            
            # Собираем ответ из потока
            full_response = ""
            for chunk in prediction:
                if chunk:
                    if isinstance(chunk, dict):
                        chunk_text = chunk.get('text', str(chunk))
                    else:
                        chunk_text = str(chunk)
                    full_response += chunk_text
            
            if full_response:
                # Добавляем сообщения в историю
                if messages_key not in st.session_state:
                    st.session_state[messages_key] = []
                
                # Добавляем сообщение пользователя
                user_message = {"role": "user", "content": question}
                st.session_state[messages_key].append(user_message)
                
                # Добавляем ответ ассистента
                assistant_message = {"role": "assistant", "content": full_response}
                st.session_state[messages_key].append(assistant_message)
                
                st.rerun()
                return {"text": full_response}
                
        except Exception as e:
            st.error(f"Ошибка при получении ответа: {str(e)}")
            return None
            
    except Exception as e:
        st.error(f"Общая ошибка: {str(e)}")
        return None

    return None

def count_api_responses():
    """Подсчет количества ответов от API в истории"""
    messages_key = get_user_messages_key()
    return sum(1 for msg in st.session_state[messages_key] if msg["role"] == "assistant")

def reset_chat_session():
    """Сброс сессии чата и очистка истории"""
    messages_key = get_user_messages_key()
    # Очищаем историю сообщений
    st.session_state[messages_key] = []
    # Генерируем новый идентификатор сессии
    st.session_state.chat_session_id = str(uuid.uuid4())
    st.rerun()

def sidebar_content():
    """Содержимое боковой панели"""
    with st.sidebar:
        # Добавляем постоянный стиль для кнопки
        st.markdown("""
            <style>
            div[data-testid="stButton"] > button[kind="secondary"] {
                background: none;
                color: inherit;
                border: 1px solid;
                padding: 6px 12px;
                font-size: 14px;
                border-radius: 4px;
                margin: 0;
                width: 100%;
            }
            </style>
        """, unsafe_allow_html=True)
        
        st.header("Управление чатом")
        
        # Отображение информации о пользователе
        if st.session_state.get("email"):
            user_avatar = get_user_profile_image(st.session_state.get("username", ""))
            col1, col2 = st.columns([1, 3])
            with col1:
                st.image(user_avatar, width=50)
            with col2:
                st.info(f"Пользователь: {st.session_state.get('email')}")
        
        # Отображение информации о лимите
        responses_count = count_api_responses()
        st.write(f"Использовано ответов: {responses_count}/{MAX_API_RESPONSES}")
        
        # Индикатор прогресса
        progress = responses_count / MAX_API_RESPONSES
        st.progress(progress)
        
        # Кнопка очистки истории с постоянным стилем
        if st.button("Очистить историю чата", 
                     use_container_width=True, 
                     type="secondary",
                     key="clear_history_button"):
            reset_chat_session()

def translate_text(text, target_lang='ru'):
    """
    Переводит текст на указанный язык
    target_lang: 'ru' для русского или 'en' для английского
    """
    try:
        translator = Translator()
        
        if text is None or not isinstance(text, str) or text.strip() == '':
            return "Пустой текст для перевода"
            
        # Определяем язык текста
        detected_lang = translator.detect(text).lang
        
        # Если текст уже на целевом языке, меняем язык перевода
        if detected_lang == target_lang:
            target_lang = 'en' if target_lang == 'ru' else 'ru'
            
        translation = translator.translate(text, dest=target_lang)
        if translation and hasattr(translation, 'text') and translation.text:
            return translation.text
            
        return f"Ошибка перевода: некорректный ответ от переводчика"
        
    except Exception as e:
        st.error(f"Ошибка при переводе: {str(e)}")
        return text

def display_message_with_translation(message):
    """Отображает сообщение с кнопкой перевода"""
    message_hash = get_message_hash(message["role"], message["content"])
    avatar = assistant_avatar if message["role"] == "assistant" else get_user_profile_image(st.session_state.get("username", ""))
    
    # Добавляем уникальный идентификатор сообщения
    if 'message_ids' not in st.session_state:
        st.session_state.message_ids = {}
    
    if message_hash not in st.session_state.message_ids:
        st.session_state.message_ids[message_hash] = len(st.session_state.message_ids)
    
    # Инициализируем состояние перевода для этого сообщения
    translation_key = f"translation_state_{message_hash}"
    if translation_key not in st.session_state:
        st.session_state[translation_key] = {
            "is_translated": False,
            "original_text": message["content"],
            "translated_text": None
        }
    
    with st.chat_message(message["role"], avatar=avatar):
        cols = st.columns([0.9, 0.1])
        
        with cols[0]:
            message_placeholder = st.empty()
            current_state = st.session_state[translation_key]
            
            if current_state["is_translated"] and current_state["translated_text"]:
                message_placeholder.markdown(current_state["translated_text"])
            else:
                message_placeholder.markdown(current_state["original_text"])
            
        with cols[1]:
            st.markdown(
                """
                <style>
                div.stButton > button {
                    width: 40px;
                    height: 40px;
                    padding: 0px;
                    border-radius: 50%;
                }
                </style>
                """,
                unsafe_allow_html=True
            )
            # Используем комбинацию хэша, ID сообщения и роли для уникального ключа
            button_key = f"translate_{message_hash}_{st.session_state.message_ids[message_hash]}_{message['role']}"
            if st.button("🔄", key=button_key, help="Перевести сообщение"):
                current_state = st.session_state[translation_key]
                
                if current_state["is_translated"]:
                    message_placeholder.markdown(current_state["original_text"])
                    st.session_state[translation_key]["is_translated"] = False
                else:
                    if not current_state["translated_text"]:
                        translated_text = translate_text(current_state["original_text"])
                        st.session_state[translation_key]["translated_text"] = translated_text
                    
                    message_placeholder.markdown(st.session_state[translation_key]["translated_text"])
                    st.session_state[translation_key]["is_translated"] = True

def get_message_hash(role, content):
    """Создает уникальный хэш для сообщения"""
    return hashlib.md5(f"{role}:{content}".encode()).hexdigest()

def main():
    # Проверка аутентификации
    if not st.session_state.get("authenticated", False):
        st.warning("Пожалуйста, войдите в систему")
        return

    # Проверка наличия API URL
    if not get_api_url():
        st.error("Ошибка конфигурации: API URL не настроен")
        return

    # Основной заголовок
    st.title("💬 Вопросы и ответы")
    st.markdown("---")

    # Получаем ключ для сообщений конкретного пользователя
    messages_key = get_user_messages_key()

    # Инициализация истории чата в session state для конкретного пользователя
    if messages_key not in st.session_state:
        st.session_state[messages_key] = []
        
    # Отображаем боковую панель
    sidebar_content()

    # Отображение истории сообщений
    for message in st.session_state[messages_key]:
        display_message_with_translation(message)

    # Проверяем лимит ответов
    if count_api_responses() >= MAX_API_RESPONSES:
        st.warning("⚠️ Достигнут лимит ответов. Пожалуйста, очистите историю чата для продолжения общения.")
        return

    # Поле ввода с возможностью растягивания
    user_input = st.text_area(
        "Введите ваше сообщение",
        height=100,
        key="message_input",
        placeholder="Введите текст сообщения здесь..."
    )

    # Создаем три колонки для кнопок
    col1, col2, col3 = st.columns(3)
    
    with col1:
        send_button = st.button("Отправить", key="send_message", use_container_width=True)
    with col2:
        clear_button = st.button("Очистить", key="clear_input", on_click=clear_input, use_container_width=True)
    with col3:
        cancel_button = st.button("Отменить", key="cancel_request", on_click=clear_input, use_container_width=True)

    # Обработка отправки сообщения
    if send_button and user_input and user_input.strip():
        st.session_state['_last_input'] = user_input
        with st.spinner('Отправляем ваш запрос...'):
            query(user_input)

if __name__ == "__main__":
    main() 
import streamlit as st
from streamlit_extras.switch_page_button import switch_page
from utils.page_config import PAGE_CONFIG, setup_pages
from utils.database.database_manager import get_database
import os
import json
from datetime import datetime

# Получаем экземпляр базы данных
db = get_database()

# Проверяем и устанавливаем состояние бокового меню
if st.session_state.get("sidebar_state") == "expanded":
    st.set_page_config(
        page_title="Ввод/Покупка ключа",
        page_icon="🔑",
        layout="wide",
        initial_sidebar_state="expanded"
    )
else:
    st.set_page_config(
        page_title="Ввод/Покупка ключа",
        page_icon="🔑",
        layout="wide",
        initial_sidebar_state="collapsed"
    )

# Затем настройка страниц
setup_pages()

# Проверка аутентификации
if "authenticated" not in st.session_state or not st.session_state.authenticated:
    st.warning("Пожалуйста, войдите в систему")
    switch_page(PAGE_CONFIG["registr"]["name"])
    st.stop()

st.title("Ввод токена")

# Поле для ввода токена
access_token = st.text_input("Вставьте токен доступа (например: b99176c5-8bca-4be9-b066-894e4103f32c)")

def verify_token(token: str, username: str) -> tuple[bool, str]:
    """Проверка и активация токена"""
    # Получаем данные пользователя
    user = db.get_user(username)
    if not user:
        return False, "Пользователь не найден"
    
    # Проверка существования и использования токена
    token_data = db.access_tokens.find_one({"token": token})
    if not token_data:
        return False, "Недействительный токен"
    
    if token_data.get("used", False):
        return False, "Токен уже использован"
    
    # Проверка использования токена другим пользователем
    existing_user = db.users.find_one({"active_token": token})
    if existing_user and existing_user['username'] != username:
        return False, "Токен уже используется другим пользователем"
    
    # Активируем токен
    try:
        # Обновляем статус токена
        db.access_tokens.update_one(
            {"token": token},
            {
                "$set": {
                    "used": True,
                    "activated_at": datetime.now(),
                    "activated_by": username
                }
            }
        )
        
        # Обновляем данные пользователя
        db.users.update_one(
            {"username": username},
            {
                "$set": {
                    "active_token": token,
                    "remaining_generations": token_data["generations"],
                    "token_activated_at": datetime.now()
                }
            }
        )
        
        return True, "Токен успешно активирован"
    except Exception as e:
        print(f"Ошибка при активации токена: {e}")
        return False, "Ошибка при активации токена"

# Проверка токена
if st.button("Активировать токен"):
    success, message = verify_token(access_token, st.session_state.username)
    if success:
        st.success(message)
        st.session_state.access_granted = True
        switch_page(PAGE_CONFIG["app"]["name"])
    else:
        st.error(message)

# Кнопка для покупки токена
if st.button("Купить токен", key="buy_link"):
    st.markdown('<a href="https://startintellect.ru/products" target="_blank">Перейти на сайт</a>', unsafe_allow_html=True)

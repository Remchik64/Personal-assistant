from st_pages import Page, show_pages, add_page_title
import streamlit as st
import os
from utils.database.database_manager import get_database
import importlib
import st_pages
import redis
import json
from datetime import timedelta
import time
from utils.redis_client import get_redis_client

# Словарь с настройками страниц
PAGE_CONFIG = {
    "registr": {
        "name": "Вход/Регистрация",
        "icon": "🔐",
        "order": 1,
        "show_when_authenticated": False,
        "show_in_menu": True
    },
    "key_input": {
        "name": "Ввод/Покупка ключа",
        "icon": "🔑",
        "order": 2,
        "show_when_authenticated": True,
        "show_in_menu": True
    },
    "simple_chat": {
        "name": "Бесплатный чат",
        "icon": "💬",
        "order": 3,
        "show_when_authenticated": True,
        "show_in_menu": True
    },
    "app": {
        "name": "Поисковый отдел",
        "icon": "🔍",
        "order": 4,
        "show_when_authenticated": True,
        "show_in_menu": True,
        "requires_token": True
    },
    "new_chat": {
        "name": "Личный помощник",
        "icon": "💭",
        "order": 5,
        "show_when_authenticated": True,
        "show_in_menu": True,
        "requires_token": True
    },
    "profile": {
        "name": "Профиль",
        "icon": "👤",
        "order": 6,
        "show_when_authenticated": True,
        "show_in_menu": True
    },
    "admin/generate_tokens": {
        "name": "Генерация ключей",
        "icon": "🔑",
        "order": 7,
        "show_when_authenticated": True,
        "show_in_menu": True,
        "admin_only": True
    },
    "admin/analytics": {
        "name": "Аналитика",
        "icon": "📊",
        "order": 8,
        "show_when_authenticated": True,
        "show_in_menu": True,
        "admin_only": True
    }
}

@st.cache_resource(show_spinner=False)
def get_pages_store():
    """Создает изолированное хранилище страниц"""
    return {}

def setup_pages():
    """Настройка страниц приложения"""
    # Проверяем состояние сессии в Redis
    redis_client = get_redis_client()
    session_id = st.session_state.get("_session_id")
    username = st.session_state.get("username", "anonymous")
    
    if redis_client and session_id and username != "anonymous":
        session_key = f"session:{username}:{session_id}"
        session_data = redis_client.get(session_key)
        
        if not session_data:
            # Если сессия не найдена в Redis, сбрасываем состояние
            st.session_state.authenticated = False
            st.session_state.username = None
            st.session_state.is_admin = False
            st.session_state._session_id = None
            show_pages([Page("pages/registr.py", name=PAGE_CONFIG["registr"]["name"], icon=PAGE_CONFIG["registr"]["icon"])])
            return
        
        # Обновляем состояние из Redis
        try:
            session_data = json.loads(session_data)
            st.session_state.authenticated = session_data.get("authenticated", False)
            st.session_state.is_admin = session_data.get("is_admin", False)
        except Exception as e:
            print(f"Ошибка при загрузке данных сессии: {e}")
    
    # Формируем список страниц
    pages_to_show = []
    is_authenticated = st.session_state.get("authenticated", False)
    is_admin = st.session_state.get("is_admin", False)
    
    # Страница регистрации для неаутентифицированных пользователей
    if not is_authenticated:
        reg_page_path = "pages/registr.py"
        if os.path.exists(reg_page_path):
            pages_to_show.append(
                Page(reg_page_path, name=PAGE_CONFIG["registr"]["name"], icon=PAGE_CONFIG["registr"]["icon"])
            )
        else:
            print(f"Ошибка: Файл {reg_page_path} не найден")
            return
    
    # Добавляем остальные страницы
    for page_id, config in sorted(PAGE_CONFIG.items(), key=lambda x: x[1]["order"]):
        if page_id == "registr":
            continue
        
        # Проверяем права доступа
        should_show = (
            is_authenticated and 
            config["show_when_authenticated"] and
            (not config.get("admin_only", False) or is_admin)
        )
        
        if should_show and config.get("show_in_menu", True):
            page_path = f"pages/{page_id}.py"
            if os.path.exists(page_path):
                pages_to_show.append(
                    Page(page_path, name=config["name"], icon=config["icon"])
                )
            else:
                print(f"Предупреждение: Файл {page_path} не найден")
    
    if not pages_to_show:
        print("Ошибка: Нет доступных страниц для отображения")
        return
        
    # Отображаем страницы
    try:
        show_pages(pages_to_show)
    except Exception as e:
        print(f"Ошибка при отображении страниц: {e}")
        # Показываем только страницу регистрации в случае ошибки
        if not is_authenticated:
            show_pages([Page("pages/registr.py", name=PAGE_CONFIG["registr"]["name"], icon=PAGE_CONFIG["registr"]["icon"])])

def check_token_access():
    """Проверка доступа к функционалу, требующему токен"""
    if not st.session_state.get("authenticated", False):
        st.warning("Пожалуйста, войдите в систему")
        st.switch_page("pages/registr.py")
        st.stop()
        
    db = get_database()
    user = db.get_user(st.session_state.get("username"))
    if not user or not user.get("active_token"):
        st.warning("Для использования этой функции необходим активный ключ")
        st.switch_page("pages/key_input.py")
        st.stop()
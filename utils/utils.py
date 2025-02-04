import json
import os
import uuid
import codecs
from datetime import datetime
from streamlit.runtime.scriptrunner import add_script_run_ctx
from streamlit import switch_page
import streamlit as st
from utils.database.database_manager import get_database

# Определяем базовый путь для файлов данных
DATA_DIR = "/data" if os.path.exists("/data") else "."

# Функция для получения правильного пути к файлу
def get_data_file_path(filename):
    """
    Возвращает полный путь к файлу данных с учетом окружения
    """
    return os.path.join(DATA_DIR, filename)

def ensure_directories():
    """Проверка и создание необходимых директорий"""
    directories = ['chat', 'profile_images', '.streamlit']
    base_dir = os.path.dirname(os.path.dirname(__file__))
    for directory in directories:
        dir_path = os.path.join(base_dir, directory)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

ensure_directories()

# Получаем экземпляр базы данных
db = get_database()

def check_token_status(username):
    """Проверяет статус токена пользователя"""
    user = db.get_user(username)
    
    if not user:
        return False, "Пользователь не найден"
        
    if not user.get('active_token'):
        return False, "Токен не активирован"
    
    # Проверяем, не был ли токен деактивирован
    if is_token_deactivated(user['active_token']):
        db.users.update_one(
            {"username": username},
            {
                "$set": {
                    "active_token": None,
                    "remaining_generations": 0,
                    "token_deactivated_at": datetime.now()
                }
            }
        )
        return False, "Токен был деактивирован"
        
    remaining_generations = user.get('remaining_generations', 0)
    if remaining_generations <= 0:
        # Деактивируем токен если генерации закончились
        save_deactivated_token(user['active_token'])
        remove_used_key(user['active_token'])
        
        db.users.update_one(
            {"username": username},
            {
                "$set": {
                    "active_token": None,
                    "remaining_generations": 0,
                    "token_deactivated_at": datetime.now()
                }
            }
        )
        return False, "Токен деактивирован: закончились генерации"
        
    return True, f"Токен активен. Осталось генераций: {remaining_generations}"

def save_token(token, generations=500):
    chat_dir = os.path.join(os.path.dirname(__file__), '..', 'chat')
    os.makedirs(chat_dir, exist_ok=True)
    keys_file = os.path.join(chat_dir, 'access_keys.json')
    
    try:
        # Проверяем, не был ли токен деактивирован ранее
        if is_token_deactivated(token):
            print(f"Попытка повторного использования деактивированного токена: {token}")
            return False
            
        # Читаем существующие данные или создаем новые
        if os.path.exists(keys_file):
            with open(keys_file, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                except:
                    data = {"keys": [], "generations": {}}
        else:
            data = {"keys": [], "generations": {}}
        
        # Добавляем токен
        token = token.strip('"')
        if token not in data["keys"]:
            data["keys"].append(token)
            # Добавляем дату активации
            if "activation_dates" not in data:
                data["activation_dates"] = {}
            data["activation_dates"][token] = datetime.now().isoformat()
            
        data["generations"][token] = generations
        
        # Сохраняем данные
        with open(keys_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Error saving token: {str(e)}")
        return False

def load_access_keys():
    chat_dir = os.path.join(os.path.dirname(__file__), '..', 'chat')
    os.makedirs(chat_dir, exist_ok=True)
    keys_file = os.path.join(chat_dir, 'access_keys.json')
    
    try:
        if os.path.exists(keys_file):
            with open(keys_file, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                    if isinstance(data, dict) and "keys" in data:
                        return data["keys"]
                except:
                    return []
        return []
    except Exception as e:
        print(f"Error loading keys: {str(e)}")
        return []

def remove_used_key(used_key):
    json_file = os.path.join(os.path.dirname(__file__), '..', 'chat', 'access_keys.json')
    
    try:
        if not os.path.exists(json_file):
            return False
        
        with open(json_file, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                data = {"keys": [], "generations": {}}
        
        if used_key in data.get('keys', []):
            data['keys'].remove(used_key)
        elif f'"{used_key}"' in data.get('keys', []):
            data['keys'].remove(f'"{used_key}"')
        
        if used_key in data.get('generations', {}):
            del data['generations'][used_key]
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Ошибка при удалении ключа: {str(e)}")
        return False

def update_remaining_generations(username, used):
    """Обновляет количество оставшихся генераций путем вычитания использованных генераций"""
    user = db.get_user(username)
    
    if not user:
        return False
    
    current_generations = user.get('remaining_generations', 0)
    
    new_remaining = current_generations - used
    
    if new_remaining <= 0:
        new_remaining = 0
        if user.get('active_token'):
            used_token = user['active_token']

            # Помечаем токен как использованный
            db.access_tokens.update_one(
                {"token": used_token},
                {"$set": {"used": True, "deactivated_at": datetime.now()}}
            )

            # Обновляем данные пользователя - деактивируем токен
            db.users.update_one(
                {"username": username},
                {
                    "$set": {
                        "active_token": None,
                        "remaining_generations": new_remaining,
                        "token_deactivated_at": datetime.now()
                    }
                }
            )

            if 'access_granted' in st.session_state:
                st.session_state.access_granted = False

            st.warning("⚠️ Ваш токен был деактивирован из-за окончания генераций. Пожалуйста, активируйте новый токен.")
    else:
        db.users.update_one(
            {"username": username},
            {
                "$set": {
                    "remaining_generations": new_remaining,
                    "last_generation_update": datetime.now()
                }
            }
        )
    
    return True

def verify_user_access():
    """Проверяет доступ пользователя"""
    if "username" not in st.session_state:
        st.warning("Необходима авторизация")
        switch_page("registr")
        return False
    
    user = db.get_user(st.session_state.username)
    if not user or not user.get('active_token'):
        st.warning("Необходим активный токен")
        switch_page("key_input")
        return False
    
    return True

def generate_unique_token():
    """Генерирует уникальный токен"""
    return str(uuid.uuid4())

def generate_and_save_token(generations=500):
    """Генерирует новый токен без сохранения в файл"""
    return generate_unique_token()

def save_deactivated_token(token):
    """Сохраняет деактивированный токен в отдельный файл"""
    deactivated_file = os.path.join(os.path.dirname(__file__), '..', 'chat', 'deactivated_keys.json')
    try:
        if os.path.exists(deactivated_file):
            with open(deactivated_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {"deactivated_keys": []}
        
        # Добавляем информацию о деактивированном токене
        token_info = {
            "token": token.strip('"'),
            "deactivated_at": datetime.now().isoformat(),
            "reason": "generations_depleted"
        }
        
        data["deactivated_keys"].append(token_info)
        
        with open(deactivated_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"Ошибка при сохранении деактивированного токена: {str(e)}")
        return False

def is_token_deactivated(token):
    """Проверяет, был ли токен деактивирован ранее"""
    deactivated_file = os.path.join(os.path.dirname(__file__), '..', 'chat', 'deactivated_keys.json')
    try:
        if os.path.exists(deactivated_file):
            with open(deactivated_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                deactivated_keys = [info["token"] for info in data.get("deactivated_keys", [])]
                return token.strip('"') in deactivated_keys
        return False
    except Exception as e:
        print(f"Ошибка при проверке деактивированного токена: {str(e)}")
        return False

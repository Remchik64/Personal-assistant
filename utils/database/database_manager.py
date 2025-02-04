import os
import json
from datetime import datetime
from typing import Dict, List, Optional
import streamlit as st
from pymongo import MongoClient
from pymongo.collection import Collection
import redis
from bson import ObjectId
from functools import wraps
import inspect

class DatabaseManager:
    _instance = None

    def __init__(self):
        # MongoDB подключение
        self.mongo_uri = st.secrets["mongodb"]["uri"]
        self.mongo_client = MongoClient(
            self.mongo_uri,
            username=st.secrets["mongodb"]["username"],
            password=st.secrets["mongodb"]["password"]
        )
        self.db = self.mongo_client[st.secrets["mongodb"]["database"]]
        
        # Коллекции MongoDB
        self.users = self.db.users
        self.chat_sessions = self.db.chat_sessions
        self.chat_history = self.db.chat_history
        self.access_tokens = self.db.access_tokens
        
        # Создаем индексы
        self._create_indexes()
        
        # Redis подключение
        self.redis_client = redis.Redis(
            host=st.secrets["redis"]["host"],
            port=st.secrets["redis"]["port"],
            password=st.secrets["redis"]["password"],
            db=st.secrets["redis"]["db"],
            decode_responses=True
        )
    
    def _create_indexes(self):
        """Создание индексов для оптимизации запросов"""
        try:
            # Индексы для пользователей
            existing_user_indexes = self.users.list_indexes()
            user_indexes = {idx['name'] for idx in existing_user_indexes}
            
            if "username_1" not in user_indexes:
                self.users.create_index("username", unique=True)
            if "email_1" not in user_indexes:
                self.users.create_index("email", unique=True)
            
            # Индексы для сессий
            existing_session_indexes = self.chat_sessions.list_indexes()
            session_indexes = {idx['name'] for idx in existing_session_indexes}
            
            if "username_1_flow_id_1_session_id_1" not in session_indexes:
                self.chat_sessions.create_index([
                    ("username", 1),
                    ("flow_id", 1),
                    ("session_id", 1)
                ], unique=True)
            
            # Индексы для истории чата
            existing_history_indexes = self.chat_history.list_indexes()
            history_indexes = {idx['name'] for idx in existing_history_indexes}
            
            if "username_1_flow_id_1_session_id_1" not in history_indexes:
                self.chat_history.create_index([
                    ("username", 1),
                    ("flow_id", 1),
                    ("session_id", 1)
                ])
            
            # Индекс для токенов
            existing_token_indexes = self.access_tokens.list_indexes()
            token_indexes = {idx['name'] for idx in existing_token_indexes}
            
            if "token_1" not in token_indexes:
                self.access_tokens.create_index("token", unique=True)
            
        except Exception as e:
            print(f"Ошибка при создании индексов: {str(e)}")
            # Не прерываем работу приложения при ошибке создания индексов
    
    def get_user(self, username: str) -> Optional[Dict]:
        """Получение данных пользователя с кэшированием"""
        cache_key = f"user:{username}"
        
        # Пробуем получить из кэша
        cached_user = self.redis_client.get(cache_key)
        if cached_user:
            return json.loads(cached_user)
        
        # Если нет в кэше, получаем из MongoDB
        user = self.users.find_one({"username": username})
        if user:
            # Кэшируем на 5 минут
            self.redis_client.setex(cache_key, 300, json.dumps(user, default=str))
        return user
    
    def update_user(self, username: str, update_data: Dict) -> bool:
        """Обновление данных пользователя с инвалидацией кэша"""
        try:
            result = self.users.update_one(
                {"username": username},
                {"$set": update_data}
            )
            
            # Инвалидируем кэш
            self.redis_client.delete(f"user:{username}")
            
            return result.modified_count > 0
        except Exception as e:
            print(f"Ошибка при обновлении пользователя: {str(e)}")
            return False
    
    def get_chat_history(self, username: str, flow_id: str, session_id: str) -> List[Dict]:
        """Получение истории чата с кэшированием"""
        cache_key = f"chat_history:{username}:{flow_id}:{session_id}"
        
        # Пробуем получить из кэша
        cached_history = self.redis_client.get(cache_key)
        if cached_history:
            return json.loads(cached_history)
        
        # Если нет в кэше, получаем из MongoDB
        history = self.chat_history.find_one({
            "username": username,
            "flow_id": flow_id,
            "session_id": session_id
        })
        
        messages = history.get("messages", []) if history else []
        
        # Кэшируем на 1 минуту
        self.redis_client.setex(cache_key, 60, json.dumps(messages, default=str))
        
        return messages
    
    def save_chat_history(self, username: str, flow_id: str, session_id: str, messages: List[Dict]) -> bool:
        """Сохранение истории чата с обновлением кэша"""
        try:
            self.chat_history.update_one(
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
            
            # Обновляем кэш
            cache_key = f"chat_history:{username}:{flow_id}:{session_id}"
            self.redis_client.setex(cache_key, 60, json.dumps(messages, default=str))
            
            return True
        except Exception as e:
            print(f"Ошибка при сохранении истории: {str(e)}")
            return False
    
    def cache_set(self, key: str, value: any, expire: int = 300):
        """Сохранение данных в кэш"""
        try:
            self.redis_client.setex(key, expire, json.dumps(value, default=str))
            return True
        except Exception as e:
            print(f"Ошибка при сохранении в кэш: {str(e)}")
            return False
    
    def cache_get(self, key: str) -> any:
        """Получение данных из кэша"""
        try:
            data = self.redis_client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            print(f"Ошибка при получении из кэша: {str(e)}")
            return None
    
    def clear_user_cache(self, username: str):
        """Очистка всего кэша пользователя"""
        try:
            # Удаляем кэш пользователя
            self.redis_client.delete(f"user:{username}")
            
            # Удаляем кэш истории чатов
            pattern = f"chat_history:{username}:*"
            keys = self.redis_client.keys(pattern)
            if keys:
                self.redis_client.delete(*keys)
            
            return True
        except Exception as e:
            print(f"Ошибка при очистке кэша: {str(e)}")
            return False
    
    def __del__(self):
        """Закрытие соединений при удалении объекта"""
        try:
            self.mongo_client.close()
            self.redis_client.close()
        except:
            pass

    def cache_handler(self, key_prefix: str, ttl: int = 300):
        """
        Декоратор для кэширования результатов функций
        """
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                # Создаем уникальный ключ кэша на основе аргументов функции
                bound_args = inspect.signature(func).bind(*args, **kwargs)
                bound_args.apply_defaults()
                cache_key = f"{key_prefix}:{func.__name__}:{hash(frozenset(bound_args.arguments.items()))}"
                
                # Пробуем получить данные из кэша
                cached_result = self.cache_get(cache_key)
                if cached_result is not None:
                    return cached_result
                
                # Если нет в кэше, выполняем функцию и сохраняем результат
                result = func(*args, **kwargs)
                self.cache_set(cache_key, result, ttl)
                return result
            return wrapper
        return decorator

def get_database() -> DatabaseManager:
    """Получение единственного экземпляра DatabaseManager"""
    if not DatabaseManager._instance:
        DatabaseManager._instance = DatabaseManager()
    return DatabaseManager._instance 
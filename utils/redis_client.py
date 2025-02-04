import redis
import streamlit as st
import socket

def is_local_environment():
    """Проверяет, запущено ли приложение локально"""
    hostname = socket.gethostname()
    return '192.168.' in socket.gethostbyname(hostname) or 'localhost' in socket.gethostbyname(hostname)

def get_redis_client():
    """Получение клиента Redis"""
    try:
        if is_local_environment():
            # Для локального тестирования всегда используем in-memory хранилище
            return InMemoryRedis()
        else:
            # Для production используем настройки из secrets
            return redis.Redis(
                host=st.secrets["redis"]["host"],
                port=st.secrets["redis"]["port"],
                password=st.secrets["redis"]["password"],
                db=st.secrets["redis"]["db"],
                decode_responses=True
            )
    except Exception as e:
        print(f"Ошибка подключения к Redis: {e}")
        if is_local_environment():
            return InMemoryRedis()
        return None

class InMemoryRedis:
    """Имитация Redis для локального тестирования"""
    def __init__(self):
        self.storage = {}
        
    def setex(self, key, time, value):
        self.storage[key] = value
        return True
        
    def get(self, key):
        return self.storage.get(key)
        
    def delete(self, key):
        if key in self.storage:
            del self.storage[key]
        return True 
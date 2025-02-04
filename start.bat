@echo off
cd /d %~dp0

:: Завершаем все процессы streamlit
taskkill /F /IM "streamlit.exe" /T 2>nul
timeout /t 2 /nobreak >nul

:: Создаем main.py для правильной маршрутизации
(
    echo import streamlit as st
    echo from streamlit_extras.switch_page_button import switch_page
    echo from utils.page_config import setup_pages, PAGE_CONFIG
    echo.
    echo # Настраиваем страницы
    echo setup_pages()
    echo.
    echo # Устанавливаем конфигурацию страницы
    echo st.set_page_config(page_title="Главная", page_icon="🏠", layout="wide", initial_sidebar_state="collapsed")
    echo.
    echo # Проверяем аутентификацию
    echo if "authenticated" in st.session_state and st.session_state.authenticated:
    echo     # Переключаемся на главную страницу приложения
    echo     switch_page(PAGE_CONFIG["app"]["name"])
    echo else:
    echo     switch_page(PAGE_CONFIG["registr"]["name"])
) > main.py

:: Запускаем streamlit с автоперезагрузкой
streamlit run main.py --server.runOnSave=true 
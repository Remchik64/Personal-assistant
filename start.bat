@echo off
cd /d %~dp0

:: Завершаем все процессы streamlit
taskkill /F /IM "streamlit.exe" /T 2>nul
timeout /t 2 /nobreak >nul

:: Создаем main.py для правильной маршрутизации
echo import streamlit as st > main.py
echo from utils.page_config import setup_pages, PAGE_CONFIG >> main.py
echo st.set_page_config(page_title="Главная", page_icon="🏠", layout="wide") >> main.py
echo setup_pages() >> main.py

:: Запускаем streamlit с автоперезагрузкой
streamlit run main.py --server.runOnSave=true 
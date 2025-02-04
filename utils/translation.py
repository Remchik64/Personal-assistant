from googletrans import Translator
import streamlit as st

# Создаем глобальный экземпляр переводчика
translator = Translator()

def translate_text(text, target_lang='ru'):
    """
    Переводит текст на указанный язык, разбивая длинный текст на части
    target_lang: 'ru' для русского или 'en' для английского
    """
    try:
        print(f"Начало перевода текста. Целевой язык: {target_lang}")
        print(f"Исходный текст (первые 100 символов): {text[:100]}...")
        
        if text is None or not isinstance(text, str) or text.strip() == '':
            print("Получен пустой текст для перевода")
            return "Пустой текст для перевода"
        
        # Создаем новый экземпляр переводчика для каждого перевода
        translator = Translator()
        
        # Определяем язык текста
        try:
            detected = translator.detect(text)
            detected_lang = detected.lang
            confidence = detected.confidence
            print(f"Определен язык: {detected_lang} (уверенность: {confidence})")
            
            # Если уверенность в определении языка низкая, используем запасной метод
            if confidence < 0.8:
                print("Низкая уверенность в определении языка, пробуем запасной метод...")
                from langdetect import detect
                detected_lang = detect(text)
                print(f"Язык определен запасным методом: {detected_lang}")
        except Exception as e:
            print(f"Ошибка при определении языка: {str(e)}")
            return text
        
        # Если текст уже на целевом языке, возвращаем его
        if detected_lang == target_lang:
            print(f"Текст уже на целевом языке ({target_lang})")
            return text
        
        # Разбиваем текст на части по 1000 символов
        print("Разбиваем текст на части...")
        parts = []
        current_part = ""
        sentences = text.replace('\n', '. ').split('. ')
        
        for sentence in sentences:
            if len(current_part) + len(sentence) < 1000:
                current_part += sentence + '. '
            else:
                if current_part:
                    parts.append(current_part.strip())
                current_part = sentence + '. '
        if current_part:
            parts.append(current_part.strip())
        
        print(f"Текст разбит на {len(parts)} частей")
        
        # Переводим каждую часть отдельно
        translated_parts = []
        for i, part in enumerate(parts, 1):
            try:
                print(f"Перевод части {i}/{len(parts)}...")
                translation = translator.translate(part, dest=target_lang)
                if translation and hasattr(translation, 'text'):
                    translated_parts.append(translation.text)
                    print(f"Часть {i} успешно переведена")
                else:
                    print(f"Ошибка: часть {i} не удалось перевести")
                    translated_parts.append(part)
            except Exception as e:
                print(f"Ошибка при переводе части {i}: {str(e)}")
                translated_parts.append(part)
                continue
        
        # Объединяем переведенные части
        result = ' '.join(translated_parts)
        print("Перевод завершен успешно")
        return result
            
    except Exception as e:
        print(f"Общая ошибка при переводе: {str(e)}")
        st.error(f"Ошибка при переводе: {str(e)}")
        return text

def display_message_with_translation(message, message_hash, avatar, role, button_key=None):
    """Отображает сообщение с кнопкой перевода"""
    # Добавляем уникальный идентификатор для каждого сообщения
    if 'message_display_counter' not in st.session_state:
        st.session_state.message_display_counter = 0
    st.session_state.message_display_counter += 1
    
    # Создаем уникальный ключ для кнопки, используя счетчик
    if button_key is None:
        button_key = f"translate_{message_hash}_{role}_{st.session_state.message_display_counter}"
    
    translation_key = f"translation_{message_hash}"
    content = message.get("content", "")
    
    with st.chat_message(role, avatar=avatar):
        cols = st.columns([0.9, 0.05, 0.05])
        
        with cols[0]:
            message_placeholder = st.empty()
            
            # Инициализируем или обновляем состояние перевода
            if translation_key not in st.session_state:
                st.session_state[translation_key] = {
                    "is_translated": False,
                    "translated_text": None,
                    "original_text": content
                }
            elif "original_text" not in st.session_state[translation_key]:
                st.session_state[translation_key].update({
                    "original_text": content
                })
            
            current_state = st.session_state[translation_key]
            
            # Отображаем текст
            if current_state["is_translated"]:
                if current_state["translated_text"] is None:
                    current_state["translated_text"] = translate_text(content)
                message_placeholder.markdown(current_state["translated_text"])
            else:
                message_placeholder.markdown(content)
        
        with cols[1]:
            # Кнопка перевода с динамической подсказкой и уникальным ключом
            try:
                detected_lang = translator.detect(content).lang
                tooltip = "Перевести на английский" if detected_lang == 'ru' else "Перевести на русский"
            except:
                tooltip = "Перевести"
                
            translate_button_key = f"{button_key}_translate_{st.session_state.message_display_counter}"
            if st.button("🔄", key=translate_button_key, help=tooltip):
                current_state = st.session_state[translation_key]
                current_state["is_translated"] = not current_state["is_translated"]
                
                if current_state["is_translated"] and current_state["translated_text"] is None:
                    current_state["translated_text"] = translate_text(content)
                
                message_placeholder.markdown(
                    current_state["translated_text"] if current_state["is_translated"] 
                    else content
                )
        
        with cols[2]:
            # Кнопка удаления с уникальным ключом
            delete_button_key = f"delete_{message_hash}_{st.session_state.message_display_counter}"
            if st.button("🗑", key=delete_button_key, help="Удалить сообщение"):
                return True
    
    return False 
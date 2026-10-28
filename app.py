import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
from datetime import datetime

# --- Настройка страницы ---
st.set_page_config(page_title="PDF Затраты: Анализ и Подсчёт", layout="wide")
st.title("📊 Анализ затрат из PDF")
st.markdown("Загрузите PDF-файлы. Приложение попытается извлечь таблицы и собрать их в общий отчёт.")

# --- Загрузка файлов ---
uploaded_files = st.file_uploader(
    "Выберите PDF-файлы (можно много)",
    type="pdf",
    accept_multiple_files=True,
    help="Загрузите все 89+ файлов сразу. Обработка может занять время."
)

if uploaded_files:
    st.info(f"Загружено файлов: {len(uploaded_files)}. Начинаю обработку...")

    all_tables_data = []  # Список для сбора всех строк из всех таблиц
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, uploaded_file in enumerate(uploaded_files):
        status_text.text(f"Обработка: {uploaded_file.name} ({i+1}/{len(uploaded_files)})")
        
        try:
            # Читаем PDF из байтов
            with pdfplumber.open(io.BytesIO(uploaded_file.read())) as pdf:
                file_has_tables = False
                
                for page_num, page in enumerate(pdf.pages, start=1):
                    tables = page.extract_tables()
                    
                    for table_idx, table in enumerate(tables):
                        if not table or len(table) < 2:
                            continue  # Пропускаем пустые или слишком короткие "таблицы"
                        
                        # Преобразуем таблицу в DataFrame
                        # Первую строку считаем заголовком (если она не пустая)
                        header = table[0]
                        # Очищаем заголовки от None и пробелов
                        header = [str(h).strip() if h else f"Колонка_{j+1}" for j, h in enumerate(header)]
                        
                        data_rows = table[1:]
                        df = pd.DataFrame(data_rows, columns=header)
                        
                        # Добавляем служебные колонки, чтобы знать, откуда данные
                        df.insert(0, "_Файл", uploaded_file.name)
                        df.insert(1, "_Страница", page_num)
                        df.insert(2, "_Таблица", table_idx + 1)
                        
                        all_tables_data.append(df)
                        file_has_tables = True
                
                if not file_has_tables:
                    # Если таблиц не нашли, добавляем запись об этом
                    all_tables_data.append(pd.DataFrame([{
                        "_Файл": uploaded_file.name,
                        "_Страница": "—",
                        "_Таблица": "—",
                        "Статус": "Таблицы не найдены (возможно, скан или нет структурированных таблиц)"
                    }]))
                    
        except Exception as e:
            # Если файл не удалось прочитать, фиксируем ошибку
            all_tables_data.append(pd.DataFrame([{
                "_Файл": uploaded_file.name,
                "_Страница": "—",
                "_Таблица": "—",
                "Ошибка": str(e)
            }]))
        
        progress_bar.progress((i + 1) / len(uploaded_files))

    status_text.text("Обработка завершена. Формирую отчёт...")

    # --- Сборка итогового отчёта ---
    if all_tables_data:
        # Объединяем все таблицы в один большой DataFrame
        # (колонки могут не совпадать, pandas выровняет их, заполнив пропуски)
        final_df = pd.concat(all_tables_data, ignore_index=True)
        
        st.subheader("📋 Предварительный просмотр извлечённых данных")
        st.dataframe(final_df.head(100))  # Показываем первые 100 строк для скорости
        
        # --- Попытка автоматического поиска числовых колонок для подсчёта ---
        st.subheader("🧮 Итоговые подсчёты (автоматическая попытка)")
        
        # Ищем колонки, которые выглядят как числовые (содержат цифры)
        numeric_cols = []
        for col in final_df.columns:
            if col.startswith("_"):  # Пропускаем служебные
                continue
            # Пробуем преобразовать в числа, убирая пробелы и запятые
            sample = final_df[col].dropna().astype(str).str.replace(' ', '').str.replace(',', '.')
            # Если хотя бы половина непустых значений — числа, считаем колонку числовой
            try:
                converted = pd.to_numeric(sample, errors='coerce')
                if converted.notna().sum() > len(converted) * 0.5:
                    numeric_cols.append(col)
            except:
                pass
        
        if numeric_cols:
            st.write(f"Найдены потенциально числовые колонки: **{', '.join(numeric_cols)}**")
            
            for col in numeric_cols:
                # Очищаем и преобразуем
                series = final_df[col].astype(str).str.replace(' ', '').str.replace(',', '.')
                numeric_series = pd.to_numeric(series, errors='coerce')
                total = numeric_series.sum()
                st.metric(label=f"Сумма по колонке «{col}»", value=f"{total:,.2f}".replace(',', ' '))
        else:
            st.warning("Автоматически числовые колонки для подсчёта не найдены. Проверьте данные вручную.")
        
        # --- Кнопка скачивания Excel ---
        st.subheader("💾 Скачать результат")
        
        # Создаём Excel в памяти
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            final_df.to_excel(writer, index=False, sheet_name='Все данные')
        output.seek(0)
        
        st.download_button(
            label="📥 Скачать Excel-файл со всеми таблицами",
            data=output,
            file_name=f"pdf_затраты_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        st.caption(f"Всего строк в отчёте: {len(final_df)}")
        
    else:
        st.error("Не удалось извлечь данные ни из одного файла.")
else:
    st.info("👆 Загрузите PDF-файлы, чтобы начать.")

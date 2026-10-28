import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
from datetime import datetime

st.set_page_config(page_title="PDF Затраты: Анализ и Подсчёт", layout="wide")
st.title("📊 Анализ затрат из PDF")
st.markdown("Загрузите PDF-счета. Приложение извлечёт товарные позиции и посчитает итоги.")


def parse_money(value):
    if value is None:
        return None
    s = str(value).strip().replace(' ', '').replace('\xa0', '')
    s = s.replace(',', '.')
    s = re.sub(r'[^\d.\-]', '', s)
    if s in ('', '.', '-'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def looks_like_item_row(row):
    if not row or len(row) < 4:
        return False
    nums = [parse_money(c) for c in row]
    numeric_count = sum(1 for n in nums if n is not None)
    has_text = any(c and len(str(c).strip()) > 3 for c in row)
    return numeric_count >= 2 and has_text


def find_header_and_cols(table):
    """Возвращает (header_row_index, col_map) или (None, None)."""
    for r_idx, row in enumerate(table[:8]):
        row_text = ' '.join(str(c) for c in row if c).lower()
        # Мягкие условия: ищем хотя бы одно слово из каждой группы
        name_words = ['товар', 'наимен', 'услуг', 'работ', 'описан']
        money_words = ['сумм', 'цена', 'стоим', 'итог']
        if any(w in row_text for w in name_words) and any(w in row_text for w in money_words):
            col_map = {}
            for j, h in enumerate(row):
                h_low = str(h).lower() if h else ''
                if any(w in h_low for w in name_words):
                    col_map.setdefault('name', j)
                elif 'кол' in h_low or 'к-во' in h_low:
                    col_map.setdefault('qty', j)
                elif 'цена' in h_low or 'стоим' in h_low:
                    col_map.setdefault('price', j)
                elif 'сумм' in h_low or 'итог' in h_low:
                    col_map.setdefault('total', j)
            if 'total' in col_map or 'price' in col_map:
                return r_idx, col_map
    return None, None


uploaded_files = st.file_uploader(
    "Выберите PDF-файлы (можно много)",
    type="pdf",
    accept_multiple_files=True,
)

if uploaded_files:
    st.info(f"Загружено файлов: {len(uploaded_files)}. Начинаю обработку...")

    all_items = []
    diagnostics = []  # для отладки: что нашли в каждом файле
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, uploaded_file in enumerate(uploaded_files):
        status_text.text(f"Обработка: {uploaded_file.name} ({i+1}/{len(uploaded_files)})")
        file_items_before = len(all_items)
        tables_found = 0
        headers_found = 0
        try:
            with pdfplumber.open(io.BytesIO(uploaded_file.read())) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        if not table or len(table) < 2:
                            continue
                        tables_found += 1
                        header_row, col_map = find_header_and_cols(table)
                        if header_row is None:
                            continue
                        headers_found += 1

                        for row in table[header_row + 1:]:
                            if not looks_like_item_row(row):
                                continue

                            def get(key):
                                idx = col_map.get(key)
                                return row[idx] if idx is not None and idx < len(row) else None

                            name = get('name')
                            qty = parse_money(get('qty'))
                            price = parse_money(get('price'))
                            total = parse_money(get('total'))

                            if total is None and price is None:
                                continue
                            if total is None and qty is not None and price is not None:
                                total = qty * price

                            all_items.append({
                                '_Файл': uploaded_file.name,
                                'Наименование': str(name).strip() if name else '',
                                'Кол-во': qty,
                                'Цена': price,
                                'Сумма': total,
                            })
        except Exception as e:
            st.warning(f"Ошибка в файле {uploaded_file.name}: {e}")

        diagnostics.append({
            'Файл': uploaded_file.name,
            'Таблиц найдено': tables_found,
            'Заголовков распознано': headers_found,
            'Позиций извлечено': len(all_items) - file_items_before,
        })
        progress_bar.progress((i + 1) / len(uploaded_files))

    status_text.text("Обработка завершена.")

    # --- Диагностика ---
    with st.expander("🔍 Диагностика: что нашлось в каждом файле", expanded=True):
        diag_df = pd.DataFrame(diagnostics)
        st.dataframe(diag_df, use_container_width=True)
        st.caption("Если у файла «Заголовков распознано» = 0 или «Позиций извлечено» = 0 — "
                   "именно этот файл нужно прислать для подгонки правил.")

    if all_items:
        final_df = pd.DataFrame(all_items)
        final_df = final_df[final_df['Сумма'].notna()].copy()

        # --- Удаление дублей счетов ---
        # Один и тот же счёт может быть в нескольких файлах: "949 (1)", "949 (2)", "949".
        # Извлекаем "базовое имя" счёта и оставляем один файл на счёт.
        def base_invoice(filename):
            name = re.sub(r'\.pdf$', '', filename, flags=re.I)
            name = re.sub(r'\s*\(\d+\)\s*', '', name)  # убираем (1), (2)
            name = re.sub(r'\s+', ' ', name).strip().lower()
            return name

        final_df['_Счёт'] = final_df['_Файл'].apply(base_invoice)
        # Сортируем так, чтобы файлы без суффикса (1)/(2) шли первыми
        final_df['_приоритет'] = final_df['_Файл'].apply(
            lambda f: 0 if not re.search(r'\(\d+\)\.pdf$', f, re.I) else 1
        )
        final_df = final_df.sort_values(['_Счёт', '_приоритет'])
        final_df = final_df.drop_duplicates(subset=['_Счёт', 'Наименование', 'Кол-во', 'Цена', 'Сумма'])
        final_df = final_df.drop(columns=['_приоритет'])

        st.subheader("📋 Товарные позиции (без дублей счетов)")
        st.dataframe(final_df.drop(columns=['_Счёт']), use_container_width=True)

        st.subheader("🧮 Итоги")
        c1, c2, c3 = st.columns(3)
        c1.metric("Всего позиций", len(final_df))
        c2.metric("Общая сумма", f"{final_df['Сумма'].sum():,.2f}".replace(',', ' '))
        c3.metric("Уникальных счетов", final_df['_Счёт'].nunique())

        st.subheader("📊 Сумма по каждому счёту")
        by_file = final_df.groupby('_Счёт', as_index=False)['Сумма'].sum()
        by_file.columns = ['Счёт', 'Итоговая сумма']
        st.dataframe(by_file, use_container_width=True)

        st.subheader("📦 Свод по наименованиям")
        by_name = (final_df.groupby('Наименование', as_index=False)
                   .agg(**{'Кол-во позиций': ('Сумма', 'count'),
                           'Итого сумма': ('Сумма', 'sum')}))
        st.dataframe(by_name, use_container_width=True)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            final_df.drop(columns=['_Счёт']).to_excel(writer, index=False, sheet_name='Позиции')
            by_file.to_excel(writer, index=False, sheet_name='Итоги по счетам')
            by_name.to_excel(writer, index=False, sheet_name='Свод по наименованиям')
            diag_df.to_excel(writer, index=False, sheet_name='Диагностика')
        output.seek(0)

        st.download_button(
            "📥 Скачать Excel (позиции + итоги + свод + диагностика)",
            data=output,
            file_name=f"затраты_свод_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.warning("Товарные строки не найдены. Возможно, PDF — сканы без текстового слоя.")
else:
    st.info("👆 Загрузите PDF-файлы, чтобы начать.")

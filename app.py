import streamlit as st
import pdfplumber
import pandas as pd
import io
import re
from datetime import datetime

st.set_page_config(page_title="PDF Затраты: Анализ и Подсчёт", layout="wide")
st.title("📊 Анализ затрат из PDF (Счета и УПД)")
st.markdown("Загрузите PDF-файлы. Приложение поддерживает обычные счета и УПД.")


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
    for r_idx, row in enumerate(table[:8]):
        row_text = ' '.join(str(c) for c in row if c).lower()
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


def extract_upd_items(text, filename):
    """Специальный парсер для УПД (ищет строку с товаром)."""
    items = []
    lines = text.split('\n')
    for line in lines:
        # Ищем строки, которые содержат код товара и ключевые слова
        if re.search(r'\d{2}-\d{8}', line) and ('щебень' in line.lower() or 'отсев' in line.lower()):
            parts = line.split()
            try:
                # Ищем индекс единицы измерения
                unit_idx = -1
                for i, p in enumerate(parts):
                    if p.lower() in ['м3', 'шт', 'т', 'кг', 'л', 'м2', 'рейс']:
                        unit_idx = i
                        break
                if unit_idx == -1:
                    continue
                
                # Количество — элемент перед единицей измерения
                qty = parse_money(parts[unit_idx - 1])
                # Цена — элемент после единицы измерения
                price = parse_money(parts[unit_idx + 1])
                
                # Сумма может быть разбита на части
                total_parts = []
                for p in parts[unit_idx + 2:]:
                    if parse_money(p) is not None:
                        total_parts.append(p)
                    else:
                        break
                
                if len(total_parts) >= 2:
                    total = parse_money(total_parts[0] + total_parts[1])
                elif len(total_parts) == 1:
                    total = parse_money(total_parts[0])
                else:
                    total = None
                
                name_parts = parts[2:unit_idx - 1]
                name = ' '.join(name_parts)
                
                if qty is not None and price is not None and total is not None:
                    items.append({
                        '_Файл': filename,
                        'Наименование': name,
                        'Кол-во': qty,
                        'Цена': price,
                        'Сумма': total,
                    })
            except (IndexError, ValueError):
                continue
    return items


uploaded_files = st.file_uploader(
    "Выберите PDF-файлы (можно много)",
    type="pdf",
    accept_multiple_files=True,
)

if uploaded_files:
    st.info(f"Загружено файлов: {len(uploaded_files)}. Начинаю обработку...")

    all_items = []
    diagnostics = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, uploaded_file in enumerate(uploaded_files):
        status_text.text(f"Обработка: {uploaded_file.name} ({i+1}/{len(uploaded_files)})")
        file_items_before = len(all_items)
        tables_found = 0
        headers_found = 0
        is_upd = False

        try:
            with pdfplumber.open(io.BytesIO(uploaded_file.read())) as pdf:
                full_text = ""
                for page in pdf.pages:
                    full_text += page.extract_text() + "\n"

                    # 1. Стандартный парсер для счетов
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

                # 2. Если стандартный парсер не нашел позиций, пробуем УПД
                if len(all_items) == file_items_before:
                    upd_items = extract_upd_items(full_text, uploaded_file.name)
                    if upd_items:
                        all_items.extend(upd_items)
                        is_upd = True
                        headers_found = len(upd_items)

        except Exception as e:
            st.warning(f"Ошибка в файле {uploaded_file.name}: {e}")

        diagnostics.append({
            'Файл': uploaded_file.name,
            'Таблиц найдено': tables_found,
            'Заголовков распознано': headers_found,
            'Позиций извлечено': len(all_items) - file_items_before,
            'Тип документа': 'УПД (спец. парсер)' if is_upd else 'Обычный счет'
        })
        progress_bar.progress((i + 1) / len(uploaded_files))

    status_text.text("Обработка завершена.")

    with st.expander("🔍 Диагностика: что нашлось в каждом файле", expanded=True):
        diag_df = pd.DataFrame(diagnostics)
        st.dataframe(diag_df, use_container_width=True)

    if all_items:
        final_df = pd.DataFrame(all_items)
        final_df = final_df[final_df['Сумма'].notna()].copy()

        # Удаление дублей (один файл на документ)
        def base_invoice(filename):
            name = re.sub(r'\.pdf$', '', filename, flags=re.I)
            name = re.sub(r'\s*\(\d+\)\s*', '', name)
            name = re.sub(r'\s+', ' ', name).strip().lower()
            return name

        final_df['_Счёт'] = final_df['_Файл'].apply(base_invoice)
        final_df['_приоритет'] = final_df['_Файл'].apply(
            lambda f: 0 if not re.search(r'\(\d+\)\.pdf$', f, re.I) else 1
        )
        final_df = final_df.sort_values(['_Счёт', '_приоритет'])
        best = final_df.groupby('_Счёт')['_приоритет'].transform('min')
        final_df = final_df[final_df['_приоритет'] == best].copy()
        final_df = final_df.drop_duplicates(subset=['_Счёт', 'Наименование', 'Кол-во', 'Цена', 'Сумма'])
        final_df = final_df.drop(columns=['_приоритет'])

        st.subheader("📋 Товарные позиции")
        st.dataframe(final_df.drop(columns=['_Счёт']), use_container_width=True)

        st.subheader("🧮 Итоги")
        c1, c2, c3 = st.columns(3)
        c1.metric("Всего позиций", len(final_df))
        c2.metric("Общая сумма", f"{final_df['Сумма'].sum():,.2f}".replace(',', ' '))
        c3.metric("Уникальных документов", final_df['_Счёт'].nunique())

        st.subheader("📊 Сумма по каждому документу")
        by_file = final_df.groupby('_Счёт', as_index=False)['Сумма'].sum()
        by_file.columns = ['Документ', 'Итоговая сумма']
        st.dataframe(by_file, use_container_width=True)

        st.subheader("📦 Свод по наименованиям")
        by_name = (final_df.groupby('Наименование', as_index=False)
                   .agg(**{'Кол-во позиций': ('Сумма', 'count'),
                           'Итого сумма': ('Сумма', 'sum')}))
        st.dataframe(by_name, use_container_width=True)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            final_df.drop(columns=['_Счёт']).to_excel(writer, index=False, sheet_name='Позиции')
            by_file.to_excel(writer, index=False, sheet_name='Итоги по документам')
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
        st.warning("Товарные строки не найдены. Проверьте диагностику.")
else:
    st.info("👆 Загрузите PDF-файлы, чтобы начать.")

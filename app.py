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
    """'7 500,00' / '18600.00' / '1 080,00' -> float"""
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
    """Строка похожа на товарную: есть текст и хотя бы 2 числа."""
    if not row or len(row) < 4:
        return False
    nums = [parse_money(c) for c in row]
    numeric_count = sum(1 for n in nums if n is not None)
    has_text = any(c and len(str(c).strip()) > 3 for c in row)
    return numeric_count >= 2 and has_text


uploaded_files = st.file_uploader(
    "Выберите PDF-файлы (можно много)",
    type="pdf",
    accept_multiple_files=True,
)

if uploaded_files:
    st.info(f"Загружено файлов: {len(uploaded_files)}. Начинаю обработку...")

    all_items = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, uploaded_file in enumerate(uploaded_files):
        status_text.text(f"Обработка: {uploaded_file.name} ({i+1}/{len(uploaded_files)})")
        try:
            with pdfplumber.open(io.BytesIO(uploaded_file.read())) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        if not table or len(table) < 2:
                            continue

                        # Ищем строку заголовка
                        header_row = None
                        for r_idx, row in enumerate(table[:6]):
                            row_text = ' '.join(str(c) for c in row if c).lower()
                            if ('товар' in row_text or 'наимен' in row_text
                                    or 'услуг' in row_text or 'работ' in row_text) \
                                    and ('сумм' in row_text or 'цена' in row_text):
                                header_row = r_idx
                                break
                        if header_row is None:
                            continue

                        header = table[header_row]
                        col_map = {}
                        for j, h in enumerate(header):
                            h_low = str(h).lower() if h else ''
                            if 'товар' in h_low or 'наимен' in h_low or 'услуг' in h_low or 'работ' in h_low:
                                col_map.setdefault('name', j)
                            elif 'кол' in h_low:
                                col_map.setdefault('qty', j)
                            elif 'цена' in h_low:
                                col_map.setdefault('price', j)
                            elif 'сумм' in h_low:
                                col_map.setdefault('total', j)

                        if 'total' not in col_map and 'price' not in col_map:
                            continue

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

        progress_bar.progress((i + 1) / len(uploaded_files))

    status_text.text("Обработка завершена.")

    if all_items:
        final_df = pd.DataFrame(all_items)
        final_df = final_df[final_df['Сумма'].notna()].copy()
        # Убираем возможные дубли (один и тот же файл мог встретиться дважды)
        final_df = final_df.drop_duplicates()

        if final_df.empty:
            st.warning("Товарные строки с суммами не найдены.")
        else:
            st.subheader("📋 Товарные позиции из всех счетов")
            st.dataframe(final_df, use_container_width=True)

            st.subheader("🧮 Итоги")
            c1, c2, c3 = st.columns(3)
            c1.metric("Всего позиций", len(final_df))
            c2.metric("Общая сумма", f"{final_df['Сумма'].sum():,.2f}".replace(',', ' '))
            c3.metric("Уникальных счетов", final_df['_Файл'].nunique())

            st.subheader("📊 Сумма по каждому счёту")
            by_file = final_df.groupby('_Файл', as_index=False)['Сумма'].sum()
            by_file.columns = ['Файл', 'Итоговая сумма']
            st.dataframe(by_file, use_container_width=True)

            st.subheader("📦 Свод по наименованиям")
            by_name = (final_df.groupby('Наименование', as_index=False)
                       .agg(**{'Кол-во позиций': ('Сумма', 'count'),
                               'Итого сумма': ('Сумма', 'sum')}))
            st.dataframe(by_name, use_container_width=True)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                final_df.to_excel(writer, index=False, sheet_name='Позиции')
                by_file.to_excel(writer, index=False, sheet_name='Итоги по счетам')
                by_name.to_excel(writer, index=False, sheet_name='Свод по наименованиям')
            output.seek(0)

            st.download_button(
                "📥 Скачать Excel (позиции + итоги + свод)",
                data=output,
                file_name=f"затраты_свод_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    else:
        st.warning("Товарные строки не найдены. Возможно, PDF — сканы без текстового слоя.")
else:
    st.info("👆 Загрузите PDF-файлы, чтобы начать.")

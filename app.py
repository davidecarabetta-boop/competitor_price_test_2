import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import google.generativeai as genai
import gspread
import json
import re
from datetime import date
import os

# --- 1. CONFIGURAZIONE ---
st.set_page_config(page_title="Sensation AI Pricing Tower", layout="wide", page_icon="📈")

if "gcp_service_account" not in st.secrets or "gemini_api_key" not in st.secrets:
    st.error("⛔ Configurazione mancante in secrets.toml")
    st.stop()

genai.configure(api_key=st.secrets["gemini_api_key"])
MODEL_NAME = 'gemini-1.5-flash'

# --- 2. FUNZIONI UTILITÀ ---
def clean_currency(value):
    if pd.isna(value) or str(value).strip() == '': return 0.0
    if isinstance(value, (int, float)): return float(value)
    s = str(value).replace('€', '').replace('$', '').strip()
    try:
        if ',' in s and '.' in s:
            if s.find('.') < s.find(','): s = s.replace('.', '').replace(',', '.')
            else: s = s.replace(',', '')
        elif ',' in s: s = s.replace(',', '.')
        return float(s)
    except: return 0.0

def clean_json_response(text):
    text = text.strip()
    if "```" in text:
        pattern = r"```(?:json)?(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match: text = match.group(1).strip()
    return text

# --- 3. CARICAMENTO DATI ---
@st.cache_data(ttl=600)
def load_data():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        client = gspread.service_account_from_dict(creds_dict)
        sh = client.open_by_url(st.secrets["google_sheets"]["sheet_url"])

        # 1. Carichiamo tutto lo storico prezzi (Foglio 1)
        df_p = pd.DataFrame(sh.sheet1.get_all_records())
        if df_p.empty: return pd.DataFrame()

        # 2. Carichiamo le entrate (Foglio Entrate)
        try: 
            df_r = pd.DataFrame(sh.worksheet("Entrate").get_all_records())
        except: 
            df_r = pd.DataFrame(columns=['Sku', 'Entrate', 'Vendite', 'Data'])

        # Mapping e Standardizzazione Colonne
        rename_map = {'Sensation_Prezzo': 'Price', 'Sensation_Posizione': 'Rank', 'Codice': 'Sku', 'id': 'Sku'}
        df_p.rename(columns=rename_map, inplace=True)
        
        for df in [df_p, df_r]:
            if not df.empty:
                df.columns = df.columns.str.strip()
                if 'Sku' in df.columns: df['Sku'] = df['Sku'].astype(str).str.strip()

        # Pulizia Valori Numerici
        for col in ['Price', 'Comp_1_Prezzo']:
            if col in df_p.columns: df_p[col] = df_p[col].apply(clean_currency)
        df_p['Rank'] = pd.to_numeric(df_p['Rank'], errors='coerce').fillna(99).astype(int)

        if not df_r.empty:
            for col in ['Entrate', 'Vendite']:
                if col in df_r.columns: df_r[col] = df_r[col].apply(clean_currency)

        # 3. GESTIONE DATE (Priorità colonna 'Data')
        for df in [df_p, df_r]:
            if not df.empty:
                col_data = 'Data' if 'Data' in df.columns else ('Data_esecuzione' if 'Data_esecuzione' in df.columns else None)
                if col_data:
                    df['Data_dt'] = pd.to_datetime(df[col_data], dayfirst=True, errors='coerce').dt.normalize()
                else:
                    df['Data_dt'] = pd.Timestamp.now().normalize()

        # 4. MERGE CRONOLOGICO (Sku + Data)
        df_final = df_p.merge(df_r, on=['Sku', 'Data_dt'], how='left', suffixes=('', '_r')).fillna(0)

        if 'Categoria' not in df_final.columns:
            df_final['Categoria'] = df_final.get('Category', 'Generale')

        return df_final.dropna(subset=['Data_dt'])
    except Exception as e:
        st.error(f"Errore caricamento: {e}")
        return pd.DataFrame()

# --- 4. FUNZIONI AI ---
def ai_clustering_bulk(df_input):
    if df_input.empty: return pd.DataFrame()
    df_subset = df_input.sort_values(by='Entrate', ascending=False).head(20)
    cols = ['Sku', 'Product', 'Price', 'Comp_1_Prezzo', 'Rank', 'Entrate']
    data_json = df_subset[cols].to_dict(orient='records')
    prompt = f"Analizza: {json.dumps(data_json)}. Definisci Categoria Strategica: 'Attacco', 'Margine', 'Monitorare', 'Liquidare'. Output JSON: [{{ 'Sku': '...', 'Categoria': '...' }}]"
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        res = model.generate_content(prompt)
        clean = clean_json_response(res.text)
        return pd.DataFrame(json.loads(clean))
    except: return pd.DataFrame()

def ai_predictive_strategy(hist_data, current_data):
    trend = "Stabile"
    if len(hist_data) > 1:
        start, end = hist_data.iloc[0]['Price'], hist_data.iloc[-1]['Price']
        trend = "In discesa" if end < start else ("In salita" if end > start else "Stabile")
    prompt = f"Prodotto: {current_data['Product']}\nPrezzo: {current_data['Price']}€ (Pos: {current_data['Rank']})\nCompetitor: {current_data['Comp_1_Prezzo']}€\nTrend: {trend}\nConsiglia strategia breve (3 righe)."
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        res = model.generate_content(prompt)
        return res.text
    except Exception as e: return f"Errore AI: {e}"

# --- 5. INTERFACCIA E FILTRI ---
df_raw = load_data()
if df_raw.empty: st.stop()

with st.sidebar:
    if os.path.exists("logosensation.png"): st.image("logosensation.png", use_container_width=True)
    else: st.title("Sensation AI")

    min_date, max_date = df_raw['Data_dt'].min().date(), df_raw['Data_dt'].max().date()
    if min_date == max_date:
        st.info(f"📅 Dati del: {min_date}")
        start_date, end_date = min_date, max_date
    else:
        date_range = st.date_input("Seleziona Periodo", [min_date, max_date])
        start_date, end_date = date_range if len(date_range) == 2 else (min_date, max_date)

    mask_date = (df_raw['Data_dt'].dt.date >= start_date) & (df_raw['Data_dt'].dt.date <= end_date)
    df_period = df_raw[mask_date].copy()
    df_latest = df_period.sort_values('Data_dt').drop_duplicates('Sku', keep='last').copy()

    sel_brands = st.multiselect("Brand", sorted(list(set([str(p).split()[0] for p in df_latest['Product'] if p]))))
    sel_cats = st.multiselect("Categoria", sorted(df_latest['Categoria'].astype(str).unique()))

    # --- FIX SICUREZZA SLIDERS ---
    def safe_slider(label, column, is_currency=False):
        val_min = float(df_latest[column].min())
        val_max = float(df_latest[column].max())
        if val_min == val_max:
            st.caption(f"{label}: {val_min:.2f}€" if is_currency else f"{label}: {val_min}")
            return (val_min, val_max)
        else:
            return st.slider(label, val_min, val_max, (val_min, val_max))

    price_range = safe_slider("Fascia di Prezzo (€)", "Price", True)
    revenue_range = safe_slider("Entrate Generate (€)", "Entrate", True)
    sales_range = safe_slider("Numero Vendite", "Vendite")

    st.divider()
    if st.button("✨ Clustering AI"):
        with st.spinner("Analisi..."): st.session_state.ai_clusters = ai_clustering_bulk(df_latest)
    if st.button("🔄 Reset Cache"):
        st.cache_data.clear()
        st.rerun()

# APPLICAZIONE FILTRI
df_filtered = df_latest.copy()
if sel_brands: df_filtered = df_filtered[df_filtered['Product'].str.contains('|'.join(sel_brands), case=False, na=False)]
if sel_cats: df_filtered = df_filtered[df_filtered['Categoria'].isin(sel_cats)]
df_filtered = df_filtered[
    (df_filtered['Price'].between(price_range[0], price_range[1])) & 
    (df_filtered['Entrate'].between(revenue_range[0], revenue_range[1])) & 
    (df_filtered['Vendite'].between(sales_range[0], sales_range[1]))
]

# --- DASHBOARD ---
st.title("🚀 Control Tower Sensation")
tab1, tab2, tab3 = st.tabs(["📊 Market Intelligence", "🔍 Focus & AI Prediction", "📈 Price vs Revenue"])

with tab1:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Win Rate", f"{(df_filtered['Rank'] == 1).mean():.1%}" if not df_filtered.empty else "0%")
    c2.metric("Pos. Media", f"{df_filtered['Rank'].mean():.1f}" if not df_filtered.empty else "0")
    c3.metric("Prezzo Medio", f"{df_filtered['Price'].mean():.2f} €" if not df_filtered.empty else "0 €")
    c4.metric("Entrate Totali", f"€ {df_filtered['Entrate'].sum():,.0f}")
    
    st.subheader("📋 Lista Prodotti")
    df_display = df_filtered.copy()
    st.dataframe(df_display[['Sku', 'Product', 'Rank', 'Price', 'Comp_1_Prezzo', 'Entrate']], use_container_width=True, hide_index=True)

with tab2:
    prods = df_filtered['Product'].unique()
    if len(prods) > 0:
        selected_prod = st.selectbox("Seleziona Prodotto:", prods)
        h_data = df_period[df_period['Product'] == selected_prod].sort_values('Data_dt')
        if st.button("🚀 Analizza SKU"): st.success(ai_predictive_strategy(h_data, h_data.iloc[-1]))
        fig_line = px.line(h_data, x='Data_dt', y=['Price', 'Comp_1_Prezzo'], markers=True, title="Andamento Prezzi")
        st.plotly_chart(fig_line, use_container_width=True)

with tab3:
    st.subheader("📈 Correlazione: Dinamica Prezzi vs Entrate")
    prods_3 = df_filtered['Product'].unique()
    if len(prods_3) > 0:
        selected_prod_3 = st.selectbox("Seleziona Prodotto:", prods_3, key="sel_tab3")
        h_data_3 = df_period[df_period['Product'] == selected_prod_3].groupby('Data_dt').agg({'Price': 'mean', 'Comp_1_Prezzo': 'mean', 'Entrate': 'sum'}).reset_index().sort_values('Data_dt')
        
        fig_3 = make_subplots(specs=[[{"secondary_y": True}]])
        fig_3.add_trace(go.Scatter(x=h_data_3['Data_dt'], y=h_data_3['Price'], name="Prezzo", mode='lines+markers', line=dict(color="#0056b3", width=3)), secondary_y=False)
        fig_3.add_trace(go.Scatter(x=h_data_3['Data_dt'], y=h_data_3['Comp_1_Prezzo'], name="Comp.", mode='lines+markers', line=dict(dash='dot')), secondary_y=False)
        fig_3.add_trace(go.Scatter(x=h_data_3['Data_dt'], y=h_data_3['Entrate'], name="Entrate", fill='tozeroy', fillcolor="rgba(40, 167, 69, 0.2)"), secondary_y=True)
        
        fig_3.update_xaxes(type='date', tickformat="%d-%m", dtick="D1", tickangle=-45)
        st.plotly_chart(fig_3, use_container_width=True)

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
        
        # Carica Prezzi
        df_p = pd.DataFrame(sh.sheet1.get_all_records())
        if df_p.empty: return pd.DataFrame()

        # Carica Entrate
        try: df_r = pd.DataFrame(sh.worksheet("Entrate").get_all_records())
        except: df_r = pd.DataFrame(columns=['Sku', 'Entrate', 'Vendite'])

        # Mapping Colonne
        rename_map = {
            'Sensation_Prezzo': 'Price',
            'Sensation_Posizione': 'Rank',
            'Codice': 'Sku', 'id': 'Sku'
        }
        df_p.rename(columns=rename_map, inplace=True)

        # Standardizza
        for df in [df_p, df_r]:
            if not df.empty:
                df.columns = df.columns.str.strip()
                if 'Sku' in df.columns: df['Sku'] = df['Sku'].astype(str).str.strip()

        # Check e Pulizia
        if 'Price' not in df_p.columns: df_p['Price'] = 0.0
        if 'Rank' not in df_p.columns: df_p['Rank'] = 99
        if 'Comp_1_Prezzo' not in df_p.columns: df_p['Comp_1_Prezzo'] = 0.0
        
        for col in ['Price', 'Comp_1_Prezzo']: df_p[col] = df_p[col].apply(clean_currency)
        df_p['Rank'] = pd.to_numeric(df_p['Rank'], errors='coerce').fillna(99).astype(int)

        if not df_r.empty:
            for col in ['Entrate', 'Vendite']:
                if col in df_r.columns: df_r[col] = df_r[col].apply(clean_currency)

        # Merge
        df_final = df_p.merge(df_r, on='Sku', how='left').fillna(0)
        
        # --- NUOVA GESTIONE DATA (FIX) ---
        # Cerchiamo la colonna 'Data' specifica del foglio storico
        if 'Data' in df_final.columns:
            df_final['Data_dt'] = pd.to_datetime(df_final['Data'], dayfirst=True, errors='coerce')
        elif 'Data_esecuzione' in df_final.columns:
            df_final['Data_dt'] = pd.to_datetime(df_final['Data_esecuzione'], dayfirst=True, errors='coerce')
        else:
            df_final['Data_dt'] = pd.Timestamp.now()
            
        # Normalizziamo (rimuoviamo l'ora) per permettere il raggruppamento corretto
        df_final['Data_dt'] = df_final['Data_dt'].dt.normalize()
            
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
    for c in cols: 
        if c not in df_subset.columns: df_subset[c] = 0
    
    data_json = df_subset[cols].to_dict(orient='records')
    prompt = f"""
    Analizza: {json.dumps(data_json)}.
    Definisci Categoria Strategica: "Attacco", "Margine", "Monitorare", "Liquidare".
    Output JSON: [{{ "Sku": "...", "Categoria": "..." }}]
    """
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
        if end < start: trend = "In discesa"
        elif end > start: trend = "In salita"

    prompt = f"""
    Prodotto: {current_data['Product']}
    Prezzo: {current_data['Price']}€ (Pos: {current_data['Rank']})
    Competitor: {current_data['Comp_1_Prezzo']}€
    Trend: {trend}
    Consiglia strategia breve (3 righe).
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        res = model.generate_content(prompt)
        return res.text
    except Exception as e: return f"Errore AI: {e}"

# --- 5. INTERFACCIA E FILTRI ---
df_raw = load_data()
if df_raw.empty: st.stop()

with st.sidebar:
    if os.path.exists("logosensation.png"):
        st.image("logosensation.png", use_container_width=True)
    else:
        st.title("Sensation AI")

    min_date = df_raw['Data_dt'].min().date()
    max_date = df_raw['Data_dt'].max().date()
    
    if min_date == max_date:
        st.info(f"📅 Dati del: {min_date}")
        start_date, end_date = min_date, max_date
    else:
        date_range = st.date_input("Seleziona Periodo", [min_date, max_date])
        if len(date_range) == 2:
            start_date, end_date = date_range
        else:
            start_date, end_date = min_date, max_date

    mask_date = (df_raw['Data_dt'].dt.date >= start_date) & (df_raw['Data_dt'].dt.date <= end_date)
    df_period = df_raw[mask_date].copy()
    df_latest = df_period.sort_values('Data_dt').drop_duplicates('Sku', keep='last').copy()

    all_brands = sorted(list(set([str(p).split()[0] for p in df_latest['Product'] if p])))
    sel_brands = st.multiselect("Brand", all_brands, default=[])
    
    all_cats = sorted(df_latest['Categoria'].astype(str).unique())
    sel_cats = st.multiselect("Categoria", all_cats, default=[])

    min_p, max_p = int(df_latest['Price'].min()), int(df_latest['Price'].max())
    if min_p == max_p: price_range = (min_p, max_p)
    else: price_range = st.slider("Fascia di Prezzo (€)", min_p, max_p, (min_p, max_p))

    min_r, max_r = int(df_latest['Entrate'].min()), int(df_latest['Entrate'].max())
    if min_r == max_r: revenue_range = (min_r, max_r)
    else: revenue_range = st.slider("Entrate Generate (€)", min_r, max_r, (min_r, max_r))

    min_v, max_v = int(df_latest['Vendite'].min()), int(df_latest['Vendite'].max())
    if min_v == max_v: sales_range = (min_v, max_v)
    else: sales_range = st.slider("Numero Vendite", min_v, max_v, (min_v, max_v))

    st.divider()
    if "ai_clusters" not in st.session_state: st.session_state.ai_clusters = pd.DataFrame()
    if st.button("✨ Clustering AI"):
        with st.spinner("Analisi..."): st.session_state.ai_clusters = ai_clustering_bulk(df_latest)
    
    if st.button("🔄 Reset Cache"):
        st.cache_data.clear()
        st.rerun()

# APPLICAZIONE FILTRI
df_filtered = df_latest.copy()
if sel_brands:
    pattern = '|'.join(sel_brands)
    df_filtered = df_filtered[df_filtered['Product'].str.contains(pattern, case=False, na=False)]
if sel_cats:
    df_filtered = df_filtered[df_filtered['Categoria'].isin(sel_cats)]
df_filtered = df_filtered[
    (df_filtered['Price'] >= price_range[0]) & (df_filtered['Price'] <= price_range[1]) &
    (df_filtered['Entrate'] >= revenue_range[0]) & (df_filtered['Entrate'] <= revenue_range[1]) &
    (df_filtered['Vendite'] >= sales_range[0]) & (df_filtered['Vendite'] <= sales_range[1])
]

# --- DASHBOARD ---
st.title("🚀 Control Tower Sensation")
st.markdown(f"**Prodotti visualizzati:** {len(df_filtered)} su {len(df_latest)}")

tab1, tab2, tab3 = st.tabs(["📊 Market Intelligence", "🔍 Focus & AI Prediction", "📈 Price vs Revenue"])

with tab1:
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df_filtered['Rank'] == 1).mean() if not df_filtered.empty else 0
    c1.metric("Win Rate", f"{win_rate:.1%}")
    c2.metric("Pos. Media", f"{df_filtered['Rank'].mean():.1f}" if not df_filtered.empty else "0")
    c3.metric("Prezzo Medio", f"{df_filtered['Price'].mean():.2f} €" if not df_filtered.empty else "0 €")
    c4.metric("Entrate Totali (Filtrate)", f"€ {df_filtered['Entrate'].sum():,.0f}")

    st.divider()
    st.subheader("Confronto Prezzi (Top 15 Filtri)")
    df_chart = df_filtered.sort_values('Entrate', ascending=False).head(15).rename(columns={'Price': 'Sensation_Prezzo'})
    if not df_chart.empty:
        fig_bar = px.bar(
            df_chart, x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], 
            barmode='group', color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'}
        )
        st.plotly_chart(fig_bar, use_container_width=True)
    else: st.warning("Nessun dato corrispondente.")

    st.subheader("📋 Lista Prodotti")
    df_display = df_filtered.copy()
    if not st.session_state.ai_clusters.empty:
        df_display = df_display.merge(st.session_state.ai_clusters, on='Sku', how='left')
        df_display['Classificazione AI'] = df_display['Categoria'].fillna("-")
    else: df_display['Classificazione AI'] = "-"
    cols_show = ['Sku', 'Product', 'Rank', 'Price', 'Comp_1_Prezzo', 'Entrate', 'Vendite', 'Classificazione AI']
    st.dataframe(df_display[cols_show].rename(columns={'Rank': 'Posizione', 'Price': 'Nostro Prezzo'}), use_container_width=True, hide_index=True)

with tab2:
    st.subheader("🔍 Analisi Storica e Predittiva")
    prods = df_filtered['Product'].unique()
    if len(prods) > 0:
        selected_prod = st.selectbox("Seleziona Prodotto:", prods)
        p_data = df_filtered[df_filtered['Product'] == selected_prod].iloc[0]
        h_data = df_period[df_period['Product'] == selected_prod].sort_values('Data_dt')

        c_info, c_ai = st.columns([1, 1])
        with c_info: st.info(f"**{selected_prod}**\n\n💰 Prezzo: {p_data['Price']}€\n\n🏆 Posizione: {p_data['Rank']}°")
        with c_ai:
            if st.button("🚀 Analizza SKU"):
                with st.spinner("AI al lavoro..."): st.success(ai_predictive_strategy(h_data, p_data))

        if not h_data.empty:
            fig_line = px.line(h_data.rename(columns={'Price': 'Sensation_Prezzo'}), x='Data_dt', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], markers=True, title="Andamento Prezzi")
            fig_line.update_xaxes(tickformat="%d-%m-%Y")
            st.plotly_chart(fig_line, use_container_width=True)
        else: st.warning("Storico insufficiente.")
    else: st.warning("Nessun prodotto disponibile.")

with tab3:
    st.subheader("📈 Correlazione: Dinamica Prezzi vs Entrate")
    prods_3 = df_filtered['Product'].unique()
    
    if len(prods_3) > 0:
        selected_prod_3 = st.selectbox("Seleziona Prodotto per analisi:", prods_3, key="sel_tab3")
        
        # Filtriamo i dati storici basandoci sul prodotto selezionato
        h_data_3 = df_period[df_period['Product'] == selected_prod_3].copy()

        if not h_data_3.empty:
            # Raggruppiamo per giorno (Data_dt) per eliminare i duplicati orari e sommare le entrate
            h_data_3 = h_data_3.groupby('Data_dt').agg({
                'Price': 'mean',
                'Comp_1_Prezzo': 'mean',
                'Entrate': 'sum'
            }).reset_index().sort_values('Data_dt')

            # Creazione grafico con doppio asse Y
            fig_3 = make_subplots(specs=[[{"secondary_y": True}]])

            # Nostro Prezzo (Asse Y1)
            fig_3.add_trace(
                go.Scatter(x=h_data_3['Data_dt'], y=h_data_3['Price'], name="Nostro Prezzo",
                           mode='lines+markers', line=dict(color="#0056b3", width=3)),
                secondary_y=False,
            )

            # Prezzo Competitor (Asse Y1)
            fig_3.add_trace(
                go.Scatter(x=h_data_3['Data_dt'], y=h_data_3['Comp_1_Prezzo'], name="Prezzo Competitor",
                           mode='lines+markers', line=dict(color="#ffa500", dash='dot')),
                secondary_y=False,
            )

            # Area Entrate (Asse Y2)
            fig_3.add_trace(
                go.Scatter(x=h_data_3['Data_dt'], y=h_data_3['Entrate'], name="Entrate (€)",
                           fill='tozeroy', mode='none', fillcolor="rgba(40, 167, 69, 0.2)"),
                secondary_y=True,
            )

            fig_3.update_xaxes(
                type='date',
                tickformat="%d-%m",
                dtick="D1",
                tickangle=-45
            )

            fig_3.update_layout(
                title_text=f"Performance Temporale: {selected_prod_3}",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )

            fig_3.update_yaxes(title_text="Prezzo (€)", secondary_y=False)
            fig_3.update_yaxes(title_text="Entrate (€)", secondary_y=True)

            st.plotly_chart(fig_3, use_container_width=True)
        else:
            st.warning("Dati storici non trovati per questo prodotto.")

import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import gspread
import json
import re

# --- 1. CONFIGURAZIONE ---
st.set_page_config(page_title="Sensation AI Pricing Tower", layout="wide", page_icon="📈")

if "gcp_service_account" not in st.secrets or "gemini_api_key" not in st.secrets:
    st.error("⛔ Configurazione mancante in secrets.toml")
    st.stop()

genai.configure(api_key=st.secrets["gemini_api_key"])
MODEL_NAME = 'gemini-1.5-flash'

# --- 2. FUNZIONI UTILITÀ (BACKEND) ---
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

# --- 3. CARICAMENTO DATI (BACKEND SICURO) ---
@st.cache_data(ttl=600)
def load_data():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        client = gspread.service_account_from_dict(creds_dict)
        sh = client.open_by_url(st.secrets["google_sheets"]["sheet_url"])
        
        # Carica Dati
        df_p = pd.DataFrame(sh.sheet1.get_all_records())
        if df_p.empty: return pd.DataFrame()
        
        try: df_r = pd.DataFrame(sh.worksheet("Entrate").get_all_records())
        except: df_r = pd.DataFrame(columns=['Sku', 'Entrate', 'Vendite'])

        # MAPPING IMPORTANTE: Rinomino le tue colonne per lavorarci facile nel codice
        # Poi nella dashboard le mostreremo come vuoi tu
        rename_map = {
            'Sensation_Prezzo': 'Price',
            'Sensation_Posizione': 'Rank',
            'Codice': 'Sku', 'id': 'Sku'
        }
        df_p.rename(columns=rename_map, inplace=True)

        # Standardizza colonne
        for df in [df_p, df_r]:
            if not df.empty:
                df.columns = df.columns.str.strip()
                if 'Sku' in df.columns: df['Sku'] = df['Sku'].astype(str).str.strip()

        # Check colonne critiche
        if 'Price' not in df_p.columns: df_p['Price'] = 0.0
        if 'Rank' not in df_p.columns: df_p['Rank'] = 99
        if 'Comp_1_Prezzo' not in df_p.columns: df_p['Comp_1_Prezzo'] = 0.0
        
        # Pulizia numeri
        for col in ['Price', 'Comp_1_Prezzo']: df_p[col] = df_p[col].apply(clean_currency)
        df_p['Rank'] = pd.to_numeric(df_p['Rank'], errors='coerce').fillna(99).astype(int)

        if not df_r.empty:
            for col in ['Entrate', 'Vendite']:
                if col in df_r.columns: df_r[col] = df_r[col].apply(clean_currency)

        # Merge
        df_final = df_p.merge(df_r, on='Sku', how='left').fillna(0)
        
        # Gestione Data
        col_data = 'Data' if 'Data' in df_final.columns else ('Data_esecuzione' if 'Data_esecuzione' in df_final.columns else None)
        if col_data: df_final['Data_dt'] = pd.to_datetime(df_final[col_data], dayfirst=True, errors='coerce')
        else: df_final['Data_dt'] = pd.Timestamp.now()
            
        return df_final.dropna(subset=['Data_dt'])
    except Exception as e:
        st.error(f"Errore caricamento: {e}")
        return pd.DataFrame()

# --- 4. FUNZIONI AI ---

def ai_clustering_bulk(df_input):
    """Analisi Clustering (ex analyze_strategy)"""
    if df_input.empty: return pd.DataFrame()
    df_subset = df_input.sort_values(by='Entrate', ascending=False).head(20)
    
    # Prepariamo dati (usando nomi interni Price/Rank)
    data_json = df_subset[['Sku', 'Product', 'Price', 'Comp_1_Prezzo', 'Rank', 'Entrate']].to_dict(orient='records')
    
    prompt = f"""
    Analizza: {json.dumps(data_json)}.
    Per ogni SKU definisci Categoria: "Attacco", "Margine", "Monitorare", "Liquidare".
    Output JSON Array: [{{ "Sku": "...", "Categoria": "..." }}]
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        res = model.generate_content(prompt)
        clean = clean_json_response(res.text)
        return pd.DataFrame(json.loads(clean))
    except: return pd.DataFrame()

def ai_predictive_strategy(hist_data, current_data):
    """Nuova funzione per Analisi Predittiva Singola"""
    trend = "Stabile"
    if len(hist_data) > 1:
        if hist_data.iloc[-1]['Price'] < hist_data.iloc[0]['Price']: trend = "Prezzo in discesa"
        elif hist_data.iloc[-1]['Price'] > hist_data.iloc[0]['Price']: trend = "Prezzo in salita"

    prompt = f"""
    Analisi prodotto: {current_data['Product']}
    Prezzo Attuale: {current_data['Price']}€
    Competitor: {current_data['Comp_1_Prezzo']}€
    Posizione Trovaprezzi: {current_data['Rank']}
    Trend storico: {trend}
    Consiglia strategia operativa (max 3 righe).
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        res = model.generate_content(prompt)
        return res.text
    except Exception as e: return f"Errore AI: {e}"

# --- 5. INTERFACCIA (INTEGRAZIONE RICHIESTA) ---

df_raw = load_data()
if df_raw.empty: st.stop()

# Snapshot dati attuali
df = df_raw.sort_values('Data_dt').drop_duplicates('Sku', keep='last').copy()

with st.sidebar:
    st.title("Sensation AI")
    brands = sorted(list(set([str(p).split()[0] for p in df['Product'] if p])))
    sel_brand = st.selectbox("Brand", ["Tutti"] + brands)
    
    st.divider()
    run_clustering = st.button("✨ Genera Clustering AI")
    
    if st.button("🔄 Aggiorna"):
        st.cache_data.clear()
        st.rerun()

# Filtro
if sel_brand != "Tutti":
    df = df[df['Product'].str.startswith(sel_brand)]

# --- DASHBOARD INTEGRATA ---
tab1, tab2 = st.tabs(["📊 Market Intelligence", "🔍 Focus & AI Prediction"])

with tab1:
    # KPI (Usiamo i nomi interni Price/Rank mappati nel load_data per sicurezza)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Win Rate", f"{(df['Rank'] == 1).mean():.1%}")
    c2.metric("Pos. Media", f"{df['Rank'].mean():.1f}")
    c3.metric("Prezzo Medio", f"{df['Price'].mean():.2f} €")
    c4.metric("SKU Analizzati", len(df))

    st.divider()

    # Grafico (Rinomino al volo per visualizzare 'Sensation_Prezzo' come chiesto)
    st.subheader("Sensation vs Competitor (Top 10)")
    df_chart = df.head(10).rename(columns={'Price': 'Sensation_Prezzo'})
    
    fig_bar = px.bar(
        df_chart, 
        x='Product', 
        y=['Sensation_Prezzo', 'Comp_1_Prezzo'], 
        barmode='group', 
        color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'}
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # Tabella Piano d'Azione
    st.subheader("📋 Piano d'Azione")
    df_display = df.copy()
    
    # Gestione AI Clustering
    if "ai_results_cache" not in st.session_state:
        st.session_state.ai_results_cache = pd.DataFrame()

    if run_clustering:
        with st.spinner("L'AI sta analizzando i dati..."):
            st.session_state.ai_results_cache = ai_clustering_bulk(df_display)

    if not st.session_state.ai_results_cache.empty:
        df_display = df_display.merge(st.session_state.ai_results_cache, on='Sku', how='left')
        df_display['Classificazione AI'] = df_display['Categoria'].fillna("Analisi non prioritaria")
    else:
        df_display['Classificazione AI'] = "Clicca 'Genera Clustering' nella sidebar"

    # Preparo tabella finale rinominando colonne interne in quelle "Utente"
    df_show = df_display[['Sku', 'Product', 'Rank', 'Price', 'Comp_1_Prezzo', 'Classificazione AI']].rename(columns={
        'Rank': 'Sensation_Posizione',
        'Price': 'Sensation_Prezzo'
    })
    
    st.dataframe(df_show, use_container_width=True, hide_index=True)

with tab2:
    st.subheader("🔍 Analisi Predittiva")
    
    prods = df['Product'].unique()
    if len(prods) > 0:
        selected_prod = st.selectbox("Seleziona Prodotto:", prods)
        
        # Dati puntuali e storici
        p_data = df[df['Product'] == selected_prod].iloc[0]
        h_data = df_raw[df_raw['Product'] == selected_prod].sort_values('Data_dt')

        col_info, col_ai = st.columns([1, 1])
        with col_info:
            st.info(f"**{selected_prod}**\n\nPrezzo Attuale: {p_data['Price']}€\n\nPosizione: {p_data['Rank']}°")
        
        with col_ai:
            if st.button("🚀 Analizza con AI"):
                with st.spinner("Analisi in corso..."):
                    analisi = ai_predictive_strategy(h_data, p_data)
                    st.success(f"**Consiglio AI:**\n\n{analisi}")

        # Grafico Trend con nomi corretti
        df_plot = h_data.rename(columns={'Price': 'Sensation_Prezzo'})
        fig_line = px.line(df_plot, x='Data_dt', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], title="Trend Storico")
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.warning("Nessun prodotto trovato.")

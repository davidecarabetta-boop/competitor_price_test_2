import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread
import google.generativeai as genai
import json

# --- 1. CONFIGURAZIONE AI ---
# Assicurati che 'gemini_api_key' sia presente nei tuoi Streamlit Secrets
genai.configure(api_key=st.secrets["gemini_api_key"])
model = genai.GenerativeModel('gemini-1.5-flash')

# --- CONFIGURAZIONE UI ---
LOGO_PATH = "logosensation.png" 
st.set_page_config(page_title="Sensation AI Pricing", layout="wide", page_icon="📈")

# --- 2. FUNZIONE CARICAMENTO DATI ---
@st.cache_data(ttl=600)
def load_data():
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_url(st.secrets["google_sheets"]["sheet_url"]).sheet1
        raw_data = sheet.get_all_values()
        
        if not raw_data: return pd.DataFrame()
        
        df = pd.DataFrame(raw_data[1:], columns=raw_data[0])
        df.columns = df.columns.str.strip()
        
        # Sincronizzazione SKU
        df['Sku'] = df['Sku'].astype(str).str.strip()

        # PULIZIA DINAMICA PREZZI
        # Identifica tutte le colonne che contengono "Prezzo" (es: Sensation_Prezzo, Comp_1_Prezzo, Comp_3_prezzo)
        price_cols = [col for col in df.columns if 'prezzo' in col.lower()]
        
        for col in price_cols:
            df[col] = (df[col].astype(str)
                       .str.replace('€', '', regex=False)
                       .str.replace('.', '', regex=False) # Rimuove separatore migliaia
                       .str.replace(',', '.', regex=False) # Converte decimale per Python
                       .str.strip())
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        # Pulizia Posizione
        if 'Sensation_Posizione' in df.columns:
            df['Sensation_Posizione'] = pd.to_numeric(df['Sensation_Posizione'], errors='coerce').fillna(0).astype(int)

        # Gestione Data
        df['Data_dt'] = pd.to_datetime(df['Data'], dayfirst=True, errors='coerce')
        return df
    except Exception as e:
        st.error(f"Errore caricamento dati: {e}")
        return pd.DataFrame()

df_raw = load_data()

# --- 3. LOGICA AI (ANALISI E PREVISIONE) ---

def ai_clustering_bulk(df_input):
    """Classifica i prodotti in base al gap di prezzo"""
    data_to_send = df_input.head(30)[['Sku', 'Product', 'Sensation_Prezzo', 'Comp_1_Prezzo']].to_dict(orient='records')
    
    prompt = f"""
    Analizza questi prodotti: {json.dumps(data_to_send)}.
    Classificali come 'Prodotto Civetta' o 'Prodotto a Margine'.
    Rispondi SOLO con una lista JSON. Esempio: [{{"Sku": "123", "Categoria": "Prodotto Civetta"}}]
    """
    try:
        response = model.generate_content(prompt)
        raw_text = response.text.strip()
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        ai_data = json.loads(raw_text)
        return pd.DataFrame(ai_data)
    except:
        return pd.DataFrame()

def ai_predictive_strategy(hist_data, p_data):
    """Analisi predittiva sul singolo prodotto"""
    trend = hist_data.tail(10)[['Data', 'Sensation_Prezzo', 'Comp_1_Prezzo']].to_string()
    prompt = f"""
    Analizza trend: {p_data['Product']}. Sensation {p_data['Sensation_Prezzo']}€, Comp {p_data['Comp_1_Prezzo']}€.
    Storico: {trend}
    Prevedi: Il competitor sta finendo lo stock? Quale prezzo impostare domani? Max 40 parole.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except:
        return "Analisi non disponibile al momento."

# --- 4. SIDEBAR E FILTRI ---
if df_raw.empty:
    st.error("Nessun dato trovato nel foglio Google.")
    st.stop()

df_latest = df_raw.sort_values('Data_dt', ascending=True).drop_duplicates('Sku', keep='last').copy()

with st.sidebar:
    try: st.image(LOGO_PATH, use_container_width=True)
    except: st.title("Sensation AI")
    
    st.header("🤖 AI Control")
    brand_list = sorted(df_raw['Product'].str.split().str[0].unique())
    selected_brands = st.multiselect("Brand", brand_list)
    run_clustering = st.button("🪄 Genera Clustering AI")
    
    if st.button("🔄 Aggiorna"):
        st.cache_data.clear()
        st.rerun()

df = df_latest.copy()
if selected_brands:
    df = df[df['Product'].str.startswith(tuple(selected_brands))]

# --- 5. DASHBOARD LAYOUT ---
tab1, tab2 = st.tabs(["📊 Market Intelligence", "🔍 Focus & AI Prediction"])

with tab1:
    # KPI
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Win Rate", f"{(df['Sensation_Posizione'] == 1).mean():.1%}")
    c2.metric("Pos. Media", f"{df['Sensation_Posizione'].mean():.1f}")
    c3.metric("Prezzo Medio", f"{df['Sensation_Prezzo'].mean():.2f} €")
    c4.metric("SKU Analizzati", len(df))

    st.divider()

    # Grafico
    st.subheader("Sensation vs Competitor (Top 10)")
    fig_bar = px.bar(df.head(10), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], 
                     barmode='group', color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'})
    st.plotly_chart(fig_bar, use_container_width=True)

    # Tabella con logica Merge AI
    st.subheader("📋 Piano d'Azione")
    df_display = df.copy()
    if run_clustering:
        with st.spinner("L'AI sta analizzando i dati..."):
            results = ai_clustering_bulk(df_display)
            if not results.empty:
                df_display = df_display.merge(results, on='Sku', how='left')
                df_display['Classificazione AI'] = df_display['Categoria'].fillna("Analisi non prioritaria")
            else:
                df_display['Classificazione AI'] = "Errore AI"
    else:
        df_display['Classificazione AI'] = "Clicca 'Genera Clustering'"

    st.dataframe(df_display[['Sku', 'Product', 'Sensation_Posizione', 'Sensation_Prezzo', 'Comp_1_Prezzo', 'Classificazione AI']], use_container_width=True, hide_index=True)

with tab2:
    st.subheader("🔍 Analisi Predittiva")
    selected_prod = st.selectbox("Seleziona Prodotto:", df['Product'].unique())
    
    p_data = df[df['Product'] == selected_prod].iloc[0]
    h_data = df_raw[df_raw['Product'] == selected_prod].sort_values('Data_dt')

    col_info, col_ai = st.columns([1, 1])
    with col_info:
        st.info(f"**{selected_prod}**\n\nPrezzo Attuale: {p_data['Sensation_Prezzo']}€\n\nPosizione: {p_data['Sensation_Posizione']}°")
    
    with col_ai:
        if st.button("🚀 Analizza con AI"):
            analisi = ai_predictive_strategy(h_data, p_data)
            st.success(f"**Consiglio AI:**\n\n{analisi}")

    st.plotly_chart(px.line(h_data, x='Data', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], title="Trend Storico"), use_container_width=True)

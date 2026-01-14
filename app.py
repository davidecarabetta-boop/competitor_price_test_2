import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread
import google.generativeai as genai
import json

# --- 1. CONFIGURAZIONE AI ---
# Assicurati che gemini_api_key sia nei Secrets di Streamlit
genai.configure(api_key=st.secrets["gemini_api_key"])
# Utilizziamo gemini-1.5-flash per velocità e costi ridotti
model = genai.GenerativeModel('gemini-2.5-flash')

# --- CONFIGURAZIONE UI ---
LOGO_PATH = "logosensation.png" 
st.set_page_config(page_title="Sensation AI Pricing", layout="wide", page_icon=LOGO_PATH)

# --- 2. CARICAMENTO DATI ---
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
        
        # Sincronizzazione SKU immediata (formato testo pulito)
        df['Sku'] = df['Sku'].astype(str).str.strip()

        # Pulizia Prezzi e Rank
        for col in ['Sensation_Prezzo', 'Comp_1_Prezzo', 'Comp_2_prezzo']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace('€', '').str.replace('.', '').str.replace(',', '.').str.strip(), errors='coerce').fillna(0)
        
        if 'Sensation_Posizione' in df.columns:
            df['Sensation_Posizione'] = pd.to_numeric(df['Sensation_Posizione'], errors='coerce').fillna(0).astype(int)

        df['Data_dt'] = pd.to_datetime(df['Data'], dayfirst=True, errors='coerce')
        return df
    except Exception as e:
        st.error(f"Errore caricamento dati: {e}")
        return pd.DataFrame()

df_raw = load_data()

# --- 3. FUNZIONI AI BLINDATE ---

def ai_clustering_v3(df_to_analyze):
    """Analisi bulk con fix per f-string e pulizia JSON"""
    # Inviamo solo i primi 30 prodotti per stabilità
    data_to_send = df_to_analyze.head(30)[['Sku', 'Product', 'Sensation_Prezzo', 'Comp_1_Prezzo']].to_dict(orient='records')
    
    # Utilizziamo {{ }} per le parentesi graffe letterali nel prompt
    prompt = f"""
    Sei un esperto di pricing per profumerie. Analizza questa lista: {json.dumps(data_to_send)}.
    Classifica ogni SKU come 'Prodotto Civetta' o 'Prodotto a Margine'.
    Rispondi SOLO con una lista JSON pura.
    Esempio: [{{ "Sku": "123", "Categoria": "Prodotto Civetta" }}]
    """
    try:
        response = model.generate_content(prompt)
        res_text = response.text.strip()
        
        # Pulizia forzata del Markdown JSON
        if "```json" in res_text:
            res_text = res_text.split("```json")[1].split("```")[0].strip()
        elif "```" in res_text:
            res_text = res_text.split("```")[1].split("```")[0].strip()
            
        ai_data = json.loads(res_text)
        # Se l'AI restituisce un singolo oggetto invece di una lista, lo incapsuliamo
        if isinstance(ai_data, dict): ai_data = [ai_data]
        
        return pd.DataFrame(ai_data)
    except Exception as e:
        st.warning(f"Errore durante l'analisi AI: {e}")
        return pd.DataFrame()

# --- 4. LOGICA SNAPSHOT & SIDEBAR ---
if df_raw.empty: st.stop()
df_latest = df_raw.sort_values('Data_dt', ascending=True).drop_duplicates('Sku', keep='last').copy()

with st.sidebar:
    try: st.image(LOGO_PATH, use_container_width=True)
    except: st.info("Sensation Intelligence")
    st.header("🤖 AI Strategy Control")
    
    brand_list = sorted(df_raw['Product'].str.split().str[0].unique())
    selected_brands = st.multiselect("Filtra per Brand", brand_list)
    
    run_clustering = st.button("🪄 Genera Clustering AI")
    
    if st.button("🔄 Aggiorna"):
        st.cache_data.clear()
        st.rerun()

df = df_latest.copy()
if selected_brands:
    df = df[df['Product'].str.startswith(tuple(selected_brands))]

# --- 5. DASHBOARD ---
tab1, tab2 = st.tabs(["📊 Market Intelligence", "🔍 Focus Prodotto"])

with tab1:
    # KPI Principali
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / len(df)) * 100 if len(df) > 0 else 0
    c1.metric("Win Rate", f"{win_rate:.1f}%")
    c2.metric("Pos. Media", f"{df['Sensation_Posizione'].mean():.1f}")
    c3.metric("Prezzo Medio", f"{df['Sensation_Prezzo'].mean():.2f}€")
    c4.metric("SKU Analizzati", len(df))

    st.divider()

    # Grafici
    col_l, col_r = st.columns([2, 1])
    with col_l:
        st.subheader("Noi vs Miglior Competitor")
        fig_bar = px.bar(df.head(15), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], 
                         barmode='group', color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'})
        st.plotly_chart(fig_bar, use_container_width=True)
    with col_r:
        st.subheader("Distribuzione Rank")
        st.plotly_chart(px.pie(df, names='Sensation_Posizione', hole=0.5), use_container_width=True)

    st.divider()

    # TABELLA CON MERGE AI
    st.subheader("📋 Piano d'Azione Strategico")
    df_display = df.copy()
    
    # Calcolo Gap % e Indice Visivo
    df_display['Gap %'] = df_display.apply(lambda x: ((x['Sensation_Prezzo'] / x['Comp_1_Prezzo']) - 1) * 100 if x['Comp_1_Prezzo'] > 0 else 0, axis=1)
    df_display['Indice'] = (df_display['Sensation_Prezzo'] / df_display['Comp_1_Prezzo'] * 100).fillna(0)
    
    if run_clustering:
        with st.spinner("L'AI sta analizzando i prodotti..."):
            ai_results = ai_clustering_v3(df_display)
            if not ai_results.empty:
                # Sincronizziamo gli SKU nei risultati AI
                ai_results['Sku'] = ai_results['Sku'].astype(str).str.strip()
                # Merge basato sullo SKU
                df_display = df_display.merge(ai_results[['Sku', 'Categoria']], on='Sku', how='left')
                df_display['Classificazione AI'] = df_display['Categoria'].fillna("Analisi non prioritaria")
            else:
                df_display['Classificazione AI'] = "❌ Errore risposta AI"
    else:
        df_display['Classificazione AI'] = "Premi 'Genera Clustering AI'"

    st.dataframe(
        df_display[['Sku', 'Product', 'Sensation_Posizione', 'Sensation_Prezzo', 'Gap %', 'Indice', 'Classificazione AI']],
        use_container_width=True, hide_index=True,
        column_config={
            "Gap %": st.column_config.NumberColumn("Gap %", format="%+.1f%%"),
            "Indice": st.column_config.ProgressColumn("Indice Comp.", min_value=80, max_value=150),
            "Sensation_Prezzo": st.column_config.NumberColumn("Prezzo Sensation", format="%.2f €")
        }
    )

with tab2:
    st.subheader("🔍 Focus Prodotto")
    if not df.empty:
        prod = st.selectbox("Seleziona Prodotto:", sorted(df['Product'].unique()))
        p_data = df[df['Product'] == prod].iloc[0]
        h_data = df_raw[df_raw['Product'] == prod].sort_values('Data_dt')

        st.info(f"**Analisi per {prod}**\n\nRank Attuale: {p_data['Sensation_Posizione']}° | Prezzo Attuale: {p_data['Sensation_Prezzo']:.2f}€")
        st.plotly_chart(px.line(h_data, x='Data', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], title="Trend Storico"), use_container_width=True)

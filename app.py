import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread
import google.generativeai as genai
import json

# --- 1. CONFIGURAZIONE AI ---
genai.configure(api_key=st.secrets["gemini_api_key"])
model = genai.GenerativeModel('gemini-1.5-flash')

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
        
        # Sincronizzazione SKU (Logica Colab)
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

# --- 3. FUNZIONI AI (Logica Colab Blindata) ---

def ai_clustering_bulk(df_input):
    """Analisi di massa per la Tabella Generale"""
    data_to_send = df_input.head(30)[['Sku', 'Product', 'Sensation_Prezzo', 'Comp_1_Prezzo']].to_dict(orient='records')
    prompt = f"""
    Analizza questi prodotti: {json.dumps(data_to_send)}.
    Classificali come 'Prodotto Civetta' o 'Prodotto a Margine'.
    Rispondi SOLO con una lista JSON. 
    Esempio: [{{ "Sku": "123", "Categoria": "Prodotto Civetta" }}]
    """
    try:
        response = model.generate_content(prompt)
        res_text = response.text.strip()
        if "```json" in res_text: res_text = res_text.split("```json")[1].split("```")[0].strip()
        ai_data = json.loads(res_text)
        df_ai = pd.DataFrame(ai_data)
        if not df_ai.empty: df_ai.columns = [c.strip().capitalize() for c in df_ai.columns]
        return df_ai
    except: return pd.DataFrame()

def ai_predictive_strategy(hist_data, p_data):
    """Analisi Predittiva e Churn Competitor per Tab 2"""
    # Analizziamo gli ultimi 10 rilevamenti per capire il trend
    trend = hist_data.tail(10)[['Data', 'Sensation_Prezzo', 'Comp_1_Prezzo']].to_string()
    
    prompt = f"""
    Analizza il trend di {p_data['Product']}.
    Dati attuali: Sensation {p_data['Sensation_Prezzo']}€, Competitor {p_data['Comp_1_Prezzo']}€.
    Storico recente:
    {trend}
    
    Compito:
    1. Prevedi se il competitor sta esaurendo le scorte (es. se il suo prezzo sale costantemente o sparisce).
    2. Suggerisci la mossa di prezzo per domani per massimizzare il profitto.
    Rispondi in max 40 parole in modo molto diretto.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except:
        return "Analisi predittiva non disponibile al momento."

# --- 4. SIDEBAR ---
if df_raw.empty: st.stop()
df_latest = df_raw.sort_values('Data_dt', ascending=True).drop_duplicates('Sku', keep='last').copy()

with st.sidebar:
    st.image(LOGO_PATH, use_container_width=True)
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
tab1, tab2 = st.tabs(["📊 Market Intelligence", "🔍 Previsione & Focus Item"])

with tab1:
    # KPI
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / len(df)) * 100 if len(df) > 0 else 0
    c1.metric("Win Rate", f"{win_rate:.1f}%")
    c2.metric("Pos. Media", f"{df['Sensation_Posizione'].mean():.1f}")
    c3.metric("Prezzo Medio", f"{df['Sensation_Prezzo'].mean():.2f}€")
    c4.metric("Prodotti", len(df))

    st.divider()

    # GRAFICI
    col_l, col_r = st.columns([2, 1])
    with col_l:
        st.plotly_chart(px.bar(df.head(15), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], barmode='group'), use_container_width=True)
    with col_r:
        st.plotly_chart(px.pie(df, names='Sensation_Posizione', hole=0.5), use_container_width=True)

    st.divider()

    # TABELLA CLUSTERING
    st.subheader("📋 Piano d'Azione AI")
    df_display = df.copy()
    df_display['Gap %'] = df_display.apply(lambda x: ((x['Sensation_Prezzo'] / x['Comp_1_Prezzo']) - 1) * 100 if x['Comp_1_Prezzo'] > 0 else 0, axis=1)
    df_display['Indice Comp.'] = (df_display['Sensation_Prezzo'] / df_display['Comp_1_Prezzo'] * 100).fillna(0)
    
    if run_clustering:
        with st.spinner("L'AI sta analizzando i prodotti..."):
            results = ai_clustering_bulk(df_display)
            if not results.empty:
                results['Sku'] = results['Sku'].astype(str).str.strip()
                df_display = df_display.merge(results[['Sku', 'Categoria']], on='Sku', how='left')
                if 'Categoria' not in df_display.columns: df_display['Categoria'] = None
            else:
                df_display['Categoria'] = None
            df_display['Classificazione AI'] = df_display['Categoria'].fillna("Analisi non prioritaria")
    else:
        df_display['Classificazione AI'] = "Usa tasto AI in sidebar"

    st.dataframe(
        df_display[['Sku', 'Product', 'Sensation_Posizione', 'Sensation_Prezzo', 'Gap %', 'Indice Comp.', 'Classificazione AI']],
        use_container_width=True, hide_index=True,
        column_config={
            "Gap %": st.column_config.NumberColumn("Gap %", format="%+.1f%%"),
            "Indice Comp.": st.column_config.ProgressColumn("Indice", format="%.0f", min_value=80, max_value=150),
        }
    )

with tab2:
    st.subheader("🔍 Previsione Churn & Strategia di Domani")
    if not df.empty:
        prod = st.selectbox("Seleziona Prodotto per l'Analisi Profonda:", sorted(df['Product'].unique()))
        p_data = df[df['Product'] == prod].iloc[0]
        h_data = df_raw[df_raw['Product'] == prod].sort_values('Data_dt')

        c_info, c_ai = st.columns([1, 1])
        with c_info:
            st.markdown(f"""
                <div style='background:#f0f2f6;padding:20px;border-radius:10px;border-left:5px solid #0056b3;'>
                    <h4>{prod}</h4>
                    <hr>
                    <p>Prezzo Attuale: <b>{p_data['Sensation_Prezzo']:.2f} €</b></p>
                    <p>Posizione TP: <b>{p_data['Sensation_Posizione']}°</b></p>
                </div>
            """, unsafe_allow_html=True)
        
        with c_ai:
            if st.button(f"🚀 Genera Previsione & Strategia AI"):
                with st.spinner("Analisi storica e predittiva in corso..."):
                    previsione = ai_predictive_strategy(h_data, p_data)
                    st.success(f"🤖 **Consiglio Strategico:**\n\n{previsione}")
        
        st.plotly_chart(px.line(h_data, x='Data', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], 
                                title=f"Trend Storico: {prod}",
                                color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'}), 
                        use_container_width=True)

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread
import google.generativeai as genai
import json

# --- 1. CONFIGURAZIONE AI GEMINI ---
# Assicurati di aver aggiunto 'gemini_api_key' nei Secrets di Streamlit
genai.configure(api_key=st.secrets["gemini_api_key"])
model = genai.GenerativeModel('gemini-1.5-flash')

# --- CONFIGURAZIONE UI & LOGO ---
LOGO_PATH = "logosensation.png" 
st.set_page_config(page_title="Sensation AI Pricing", layout="wide", page_icon=LOGO_PATH)

# --- 2. CARICAMENTO E PULIZIA DATI (Blindata) ---
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

        # Conversione Numerica (Virgola -> Punto)
        for col in ['Sensation_Prezzo', 'Comp_1_Prezzo', 'Comp_2_prezzo']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace('€', '').str.replace('.', '').str.replace(',', '.').str.strip(), errors='coerce').fillna(0)
        
        if 'Sensation_Posizione' in df.columns:
            df['Sensation_Posizione'] = pd.to_numeric(df['Sensation_Posizione'], errors='coerce').fillna(0).astype(int)

        df['Data_dt'] = pd.to_datetime(df['Data'], dayfirst=True, errors='coerce')
        return df
    except Exception as e:
        st.error(f"Errore caricamento: {e}")
        return pd.DataFrame()

df_raw = load_data()

# --- 3. FUNZIONI AI AVANZATE (GEMINI) ---

def ai_cluster_products(df_current):
    """Usa Gemini per classificare il catalogo in Civetta o Margine"""
    # Prepariamo un riassunto dei dati per l'AI
    data_summary = df_current[['Sku', 'Product', 'Sensation_Prezzo', 'Comp_1_Prezzo', 'Sensation_Posizione']].to_json()
    
    prompt = f"""
    Analizza questi dati di pricing di una profumeria: {data_summary}.
    Dividi i prodotti in due categorie: 
    1. 'Prodotto Civetta' (Alta competizione, Rank > 1 o distacco minimo, serve ad attirare traffico).
    2. 'Prodotto a Margine' (Bassa competizione, sei primo con buon distacco o competitor assenti).
    Restituisci SOLO un oggetto JSON dove la chiave è lo SKU e il valore è la categoria.
    """
    try:
        response = model.generate_content(prompt)
        # Pulizia della risposta per estrarre solo il JSON
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except:
        return {}

def ai_predict_stock_out(hist_data, product_name):
    """Usa Gemini per prevedere il churn (fine scorte) del competitor"""
    trend = hist_data[['Data', 'Comp_1_Prezzo']].to_string()
    
    prompt = f"""
    Analizza lo storico prezzi del competitor per il prodotto {product_name}:
    {trend}
    Se vedi che il prezzo del competitor sale improvvisamente o sparisce (va a 0), 
    è probabile che stia finendo le scorte. 
    Fornisci una previsione breve (max 20 parole) e consiglia se alzare il prezzo di Sensation.
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except:
        return "Analisi AI non disponibile al momento."

# --- 4. LOGICA SNAPSHOT & SIDEBAR ---
if df_raw.empty: st.stop()
df_latest = df_raw.sort_values('Data_dt', ascending=True).drop_duplicates('Sku', keep='last').copy()

with st.sidebar:
    st.image(LOGO_PATH, use_container_width=True)
    st.header("🤖 AI Strategy Control")
    full_brand_list = sorted(df_raw['Product'].str.split().str[0].unique())
    selected_brands = st.multiselect("Filtra per Brand", full_brand_list)
    
    run_clustering = st.button("🪄 Genera Clustering AI")
    
    if st.button("🔄 Aggiorna Dati"):
        st.cache_data.clear()
        st.rerun()

df = df_latest.copy()
if selected_brands:
    df = df[df['Product'].str.startswith(tuple(selected_brands))]

# --- 5. DASHBOARD ---
tab1, tab2 = st.tabs(["📊 Market Intelligence", "🔍 AI Deep Dive"])

with tab1:
    # KPI e Grafici Classici
    # ... (Mantieni i 4 KPI e i 2 grafici visti prima) ...
    
    st.subheader("📋 Piano d'Azione AI")
    
    # Eseguiamo il clustering se l'utente preme il tasto
    if run_clustering:
        with st.spinner("L'AI sta analizzando il mercato..."):
            clusters = ai_cluster_products(df)
            df['AI_Category'] = df['Sku'].map(clusters).fillna("In Analisi...")
    else:
        df['AI_Category'] = "Clicca 'Genera Clustering AI'"

    # Super Tabella con Clustering AI
    st.dataframe(
        df[['Sku', 'Product', 'Sensation_Posizione', 'Sensation_Prezzo', 'AI_Category']],
        use_container_width=True,
        hide_index=True,
        column_config={
            "AI_Category": st.column_config.TextColumn("🏷️ Tipo Prodotto (AI)", width="medium")
        }
    )

with tab2:
    st.subheader("🔍 Previsione Churn & Trend")
    product_selected = st.selectbox("Analizza Prodotto:", df['Product'].unique())
    
    p_data = df[df['Product'] == product_selected].iloc[0]
    hist_data = df_raw[df_raw['Product'] == product_selected].sort_values('Data_dt')

    col_card, col_ai = st.columns([1, 2])
    
    with col_card:
        st.markdown(f"""
            <div style="background-color: #f0f2f6; padding: 20px; border-radius: 10px;">
                <h3>{product_selected}</h3>
                <p>Prezzo Attuale: <b>{p_data['Sensation_Prezzo']:.2f} €</b></p>
                <p>Rank: <b>{p_data['Sensation_Posizione']}°</b></p>
            </div>
        """, unsafe_allow_html=True)
        
    with col_ai:
        st.info("🧠 **Analisi Predittiva Gemini AI**")
        prediction = ai_predict_stock_out(hist_data, product_selected)
        st.write(prediction)
    
    st.plotly_chart(px.line(hist_data, x='Data', y=['Sensation_Prezzo', 'Comp_1_Prezzo']), use_container_width=True)

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread
import google.generativeai as genai
import json

# --- 1. CONFIGURAZIONE AI GEMINI ---
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

# --- 3. FUNZIONI AI OTTIMIZZATE ---
def ai_analyze_brand(df_filtered, brand_name):
    """Analisi strategica per un intero Brand"""
    data_json = df_filtered.head(40)[['Sku', 'Product', 'Sensation_Prezzo', 'Comp_1_Prezzo', 'Sensation_Posizione']].to_json()
    prompt = f"""
    Sei un Pricing Manager. Analizza i dati del brand {brand_name}: {data_json}.
    Classifica gli SKU in 'Civetta' (basso margine per attirare click) o 'Margine' (sei leader, alza il prezzo).
    Rispondi SOLO con un JSON: {{"SKU": "Categoria"}}
    """
    try:
        response = model.generate_content(prompt)
        raw_text = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(raw_text)
    except: return {}

def ai_deep_product_strategy(hist_data, p_data):
    """Strategia avanzata per singolo Prodotto"""
    trend = hist_data.tail(10)[['Data', 'Sensation_Prezzo', 'Comp_1_Prezzo']].to_string()
    prompt = f"""
    Analizza il prodotto {p_data['Product']}. 
    Dati attuali: Prezzo Sensation {p_data['Sensation_Prezzo']}€, Posizione {p_data['Sensation_Posizione']}°. 
    Storico recente: {trend}.
    Suggerisci l'azione di prezzo esatta per domani per massimizzare il profitto. (max 30 parole)
    """
    try: return model.generate_content(prompt).text
    except: return "Analisi non disponibile."

# --- 4. LOGICA SNAPSHOT & SIDEBAR ---
if df_raw.empty: st.stop()
df_latest = df_raw.sort_values('Data_dt', ascending=True).drop_duplicates('Sku', keep='last').copy()

with st.sidebar:
    try: st.image(LOGO_PATH, use_container_width=True)
    except: st.info("Sensation Intelligence")
    
    st.header("🤖 AI Strategy Control")
    brand_list = sorted(df_raw['Product'].str.split().str[0].unique())
    selected_brands = st.multiselect("Filtra per Brand", brand_list)
    
    # Il tasto ora è dinamico: se selezioni un brand, analizza solo quello
    label_tasto = f"Analizza Brand {selected_brands[0]}" if (selected_brands and len(selected_brands)==1) else "Analizza Catalogo Visibile"
    run_clustering = st.button(f"🪄 {label_tasto}")

# Filtro Brand applicato a tutto
df = df_latest.copy()
if selected_brands:
    df = df[df['Product'].str.startswith(tuple(selected_brands))]

# --- 5. DASHBOARD ---
tab1, tab2 = st.tabs(["📊 Overview Mercato", "🔍 Focus Prodotto"])

with tab1:
    # KPI e Grafici (sempre presenti)
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / len(df)) * 100 if len(df) > 0 else 0
    c1.metric("Buy Box Win Rate", f"{win_rate:.1f}%")
    c2.metric("Posizione Media", f"{df['Sensation_Posizione'].mean():.1f}")
    c3.metric("Prezzo Sensation Medio", f"{df['Sensation_Prezzo'].mean():.2f}€")
    c4.metric("Prodotti Visualizzati", len(df))

    st.divider()
    
    # Calcolo Gap % (per togliere quel 142 e mettere +42%)
    df_display = df.copy()
    df_display['Gap_%'] = df_display.apply(lambda x: ((x['Sensation_Prezzo'] / x['Comp_1_Prezzo']) - 1) * 100 if x['Comp_1_Prezzo'] > 0 else 0, axis=1)

    if run_clustering:
        with st.spinner("L'AI sta analizzando i dati selezionati..."):
            brand_name = selected_brands[0] if selected_brands else "Generale"
            clusters = ai_analyze_brand(df, brand_name)
            df_display['AI_Category'] = df_display['Sku'].map(clusters).fillna("Standard")
    else:
        df_display['AI_Category'] = "Usa il tasto nella sidebar"

    st.subheader("📋 Piano d'Azione Strategico")
    st.dataframe(
        df_display[['Sku', 'Product', 'Sensation_Posizione', 'Sensation_Prezzo', 'Gap_%', 'AI_Category']],
        use_container_width=True, hide_index=True,
        column_config={
            "Gap_%": st.column_config.NumberColumn("Gap %", format="%+.1f%%", help="Differenza rispetto al 1° competitor"),
            "AI_Category": st.column_config.TextColumn("🏷️ Tipo Prodotto (AI)")
        }
    )

with tab2:
    st.subheader("🔍 Focus Prodotto & Strategia AI")
    if not df.empty:
        prod = st.selectbox("Seleziona Prodotto:", df['Product'].unique())
        p_data = df[df['Product'] == prod].iloc[0]
        h_data = df_raw[df_raw['Product'] == prod].sort_values('Data_dt')

        col_info, col_ai_action = st.columns([1, 1])
        
        with col_info:
            st.markdown(f"""
                <div style='background:#f0f2f6;padding:20px;border-radius:10px;'>
                    <h4>{prod}</h4>
                    <p>Prezzo: <b>{p_data['Sensation_Prezzo']:.2f} €</b> | Rank: <b>{p_data['Sensation_Posizione']}°</b></p>
                </div>
            """, unsafe_allow_html=True)
        
        with col_ai_action:
            # TASTO AI PER SINGOLO PRODOTTO
            if st.button(f"🚀 Richiedi Strategia per {prod.split()[0]}..."):
                with st.spinner("Gemini sta calcolando la mossa vincente..."):
                    st.success(ai_deep_product_strategy(h_data, p_data))
        
        st.plotly_chart(px.line(h_data, x='Data', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], title="Analisi Storica Prezzi"), use_container_width=True)

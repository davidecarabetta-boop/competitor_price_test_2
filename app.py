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

        # Pulizia Prezzi e Rank
        for col in ['Sensation_Prezzo', 'Comp_1_Prezzo', 'Comp_2_prezzo']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace('€', '').str.replace('.', '').str.replace(',', '.').str.strip(), errors='coerce').fillna(0)
        
        if 'Sensation_Posizione' in df.columns:
            df['Sensation_Posizione'] = pd.to_numeric(df['Sensation_Posizione'], errors='coerce').fillna(0).astype(int)

        df['Data_dt'] = pd.to_datetime(df['Data'], dayfirst=True, errors='coerce')
        return df
    except Exception as e:
        st.error(f"Errore database: {e}")
        return pd.DataFrame()

df_raw = load_data()

# --- 3. FUNZIONI AI POTENZIATE (MATCHING FORZATO) ---

def ai_analyze_bulk(df_to_analyze, scope_name):
    """Invia i dati a Gemini e forza il formato JSON"""
    # Prendiamo al massimo 50 prodotti, ma se sono meno analizziamo tutto
    data_list = df_to_analyze.head(50)[['Sku', 'Product', 'Sensation_Prezzo', 'Comp_1_Prezzo', 'Sensation_Posizione']].to_dict(orient='records')
    
    prompt = f"""
    Analizza questi prodotti ({scope_name}): {json.dumps(data_list)}.
    Classifica ogni SKU in:
    1. 'Prodotto Civetta': Alta competizione, serve a generare traffico.
    2. 'Prodotto a Margine': Bassa competizione o distacco alto.
    
    Rispondi esclusivamente con un JSON piatto. Esempio: {{"12345": "Prodotto Civetta"}}.
    NON cambiare il formato degli SKU.
    """
    try:
        response = model.generate_content(prompt)
        # Pulizia rigorosa della risposta
        res_text = response.text.strip()
        if "```json" in res_text:
            res_text = res_text.split("```json")[1].split("```")[0].strip()
        return json.loads(res_text)
    except:
        return {}

def ai_single_item_strategy(hist_data, p_data):
    """Strategia specifica per singolo prodotto"""
    trend = hist_data.tail(10)[['Data', 'Sensation_Prezzo', 'Comp_1_Prezzo']].to_string()
    prompt = f"Analizza {p_data['Product']}. Prezzo {p_data['Sensation_Prezzo']}€, Posizione {p_data['Sensation_Posizione']}°. Storico: {trend}. Suggerisci azione di prezzo e categoria (Civetta/Margine) in 30 parole."
    try: return model.generate_content(prompt).text
    except: return "Analisi non disponibile."

# --- 4. SIDEBAR & LOGICA ---
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
tab1, tab2 = st.tabs(["📊 Market Intelligence", "🔍 Focus Prodotto"])

with tab1:
    # KPI
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / len(df)) * 100 if len(df) > 0 else 0
    c1.metric("Win Rate", f"{win_rate:.1f}%")
    c2.metric("Pos. Media", f"{df['Sensation_Posizione'].mean():.1f}")
    c3.metric("Prezzo Medio", f"{df['Sensation_Prezzo'].mean():.2f}€")
    c4.metric("Prodotti", len(df))

    # Grafici
    col_l, col_r = st.columns([2, 1])
    with col_l:
        st.plotly_chart(px.bar(df.head(15), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], barmode='group'), use_container_width=True)
    with col_r:
        st.plotly_chart(px.pie(df, names='Sensation_Posizione', hole=0.5), use_container_width=True)

    # TABELLA CON MATCHING SKU FORZATO
    st.subheader("📋 Piano d'Azione AI")
    df_display = df.copy()
    df_display['Sku'] = df_display['Sku'].astype(str).str.strip() # Pulizia SKU
    
    # Gap e Posizionamento
    df_display['Gap %'] = df_display.apply(lambda x: ((x['Sensation_Prezzo'] / x['Comp_1_Prezzo']) - 1) * 100 if x['Comp_1_Prezzo'] > 0 else 0, axis=1)
    df_display['Indice'] = (df_display['Sensation_Prezzo'] / df_display['Comp_1_Prezzo'] * 100).fillna(0)
    
    if run_clustering:
        with st.spinner("Analisi AI in corso..."):
            scope = selected_brands[0] if selected_brands else "Catalogo"
            raw_clusters = ai_analyze_bulk(df_display, scope)
            # Normalizziamo le chiavi del dizionario AI per il matching
            clusters_clean = {str(k).strip(): v for k, v in raw_clusters.items()}
            df_display['Classificazione AI'] = df_display['Sku'].map(clusters_clean).fillna("⚠️ SKU non riconosciuto dall'AI")
    else:
        df_display['Classificazione AI'] = "Premi 'Genera Clustering AI'"

    st.dataframe(
        df_display[['Sku', 'Product', 'Sensation_Posizione', 'Sensation_Prezzo', 'Gap %', 'Indice', 'Classificazione AI']],
        use_container_width=True, hide_index=True,
        column_config={
            "Gap %": st.column_config.NumberColumn("Gap %", format="%+.1f%%"),
            "Indice": st.column_config.ProgressColumn("Indice Comp.", min_value=80, max_value=150),
        }
    )

with tab2:
    st.subheader("🔍 Focus Prodotto & Strategia")
    if not df.empty:
        prod = st.selectbox("Seleziona Prodotto:", sorted(df['Product'].unique()))
        p_data = df[df['Product'] == prod].iloc[0]
        h_data = df_raw[df_raw['Product'] == prod].sort_values('Data_dt')

        c_info, c_ai = st.columns([1, 1])
        with c_info:
            st.info(f"**{prod}**\n\nRank: {p_data['Sensation_Posizione']}°\n\nPrezzo: {p_data['Sensation_Prezzo']:.2f}€")
        with c_ai:
            if st.button("🚀 Richiedi Strategia AI"):
                st.success(ai_single_item_strategy(h_data, p_data))
        
        st.plotly_chart(px.line(h_data, x='Data', y=['Sensation_Prezzo', 'Comp_1_Prezzo']), use_container_width=True)

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
        st.error(f"Errore caricamento: {e}")
        return pd.DataFrame()

df_raw = load_data()

# --- 3. FUNZIONI AI CONTESTUALI (OTTIMIZZATE) ---

def ai_analyze_market(df_filtered, scope_name):
    """Analisi Clustering con forzatura SKU stringa per evitare 'Standard'"""
    # Selezioniamo i 30 prodotti più critici (Gap più alto) per l'analisi
    df_sample = df_filtered.copy()
    df_sample['Gap_Tmp'] = ((df_sample['Sensation_Prezzo'] / df_sample['Comp_1_Prezzo']) - 1)
    df_analysis = df_sample.sort_values('Gap_Tmp', ascending=False).head(30)
    
    data_json = df_analysis[['Sku', 'Product', 'Sensation_Prezzo', 'Comp_1_Prezzo', 'Sensation_Posizione']].to_json(orient='records')
    
    prompt = f"""
    Analizza questi prodotti ({scope_name}): {data_json}.
    Classifica ogni SKU esclusivamente come:
    1. 'Prodotto Civetta': Se la competizione è estrema o il prezzo è molto vicino al leader.
    2. 'Prodotto a Margine': Se abbiamo spazio per alzare il prezzo o siamo leader isolati.
    
    Rispondi SOLO con un JSON piatto. Esempio: {{"SKU": "Categoria"}}.
    Usa esattamente gli SKU forniti.
    """
    try:
        response = model.generate_content(prompt)
        raw_text = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(raw_text)
    except:
        return {}

def ai_single_item_strategy(hist_data, p_data):
    """Analisi Churn e Strategia specifica per singolo prodotto"""
    trend = hist_data.tail(10)[['Data', 'Sensation_Prezzo', 'Comp_1_Prezzo']].to_string()
    
    prompt = f"""
    Analizza il prodotto: {p_data['Product']}. 
    Prezzo attuale {p_data['Sensation_Prezzo']}€, Posizione {p_data['Sensation_Posizione']}°. 
    Trend storico: {trend}.
    1. Prevedi se il competitor sta per finire le scorte (churn) analizzando se il suo prezzo sale o sparisce.
    2. Suggerisci l'azione di prezzo per domani per massimizzare il profitto.
    Rispondi in max 35 parole.
    """
    try:
        return model.generate_content(prompt).text
    except:
        return "Analisi AI non disponibile al momento."

# --- 4. LOGICA SNAPSHOT & SIDEBAR ---
if df_raw.empty: st.stop()
df_latest = df_raw.sort_values('Data_dt', ascending=True).drop_duplicates('Sku', keep='last').copy()

with st.sidebar:
    try: st.image(LOGO_PATH, use_container_width=True)
    except: st.info("Sensation Intelligence")
    st.header("🤖 AI Strategy Control")
    brand_list = sorted(df_raw['Product'].str.split().str[0].unique())
    selected_brands = st.multiselect("Filtra per Brand", brand_list)
    
    # Tasto dinamico per analisi Brand o Globale
    run_clustering = st.button("🪄 Genera Clustering AI")
    
    if st.button("🔄 Aggiorna Dati"):
        st.cache_data.clear()
        st.rerun()

df = df_latest.copy()
if selected_brands:
    df = df[df['Product'].str.startswith(tuple(selected_brands))]

# --- 5. DASHBOARD ---
tab1, tab2 = st.tabs(["📊 Overview Mercato", "🔍 Focus Prodotto"])

# --- TAB 1: OVERVIEW INTEGRATA ---
with tab1:
    # KPI
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / len(df)) * 100 if len(df) > 0 else 0
    c1.metric("Buy Box Win Rate", f"{win_rate:.1f}%")
    c2.metric("Posizione Media", f"{df['Sensation_Posizione'].mean():.1f}")
    c3.metric("Prezzo Sensation Medio", f"{df['Sensation_Prezzo'].mean():.2f}€")
    c4.metric("Prodotti Visualizzati", len(df))

    st.divider()

    # GRAFICI
    col_l, col_r = st.columns([2, 1])
    with col_l:
        st.subheader("Noi vs Miglior Competitor")
        fig_bar = px.bar(df.head(15), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], 
                         barmode='group', color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'})
        st.plotly_chart(fig_bar, use_container_width=True)
    with col_r:
        st.subheader("Distribuzione Rank")
        fig_pie = px.pie(df, names='Sensation_Posizione', hole=0.5)
        st.plotly_chart(fig_pie, use_container_width=True)

    st.divider()

    # TABELLA AI & COMPETITIVITÀ
    st.subheader("📋 Piano d'Azione AI & Competitività")
    df_display = df.copy()
    
    # Calcolo Gap in Percentuale (+/- %)
    df_display['Gap %'] = df_display.apply(lambda x: ((x['Sensation_Prezzo'] / x['Comp_1_Prezzo']) - 1) * 100 if x['Comp_1_Prezzo'] > 0 else 0, axis=1)
    df_display['Indice Comp.'] = (df_display['Sensation_Prezzo'] / df_display['Comp_1_Prezzo'] * 100).fillna(0)
    
    # Sincronizzazione SKU per il matching AI
    df_display['Sku'] = df_display['Sku'].astype(str)
    
    if run_clustering:
        with st.spinner("L'AI sta analizzando i prodotti più critici..."):
            scope_name = selected_brands[0] if selected_brands else "Catalogo Globale"
            clusters = ai_analyze_market(df, scope_name)
            # Pulizia chiavi JSON per matching sicuro
            clusters_clean = {str(k): v for k, v in clusters.items()}
            df_display['AI_Category'] = df_display['Sku'].map(clusters_clean).fillna("Analisi non prioritaria")
    else:
        df_display['AI_Category'] = "Usa tasto AI in sidebar"

    st.dataframe(
        df_display[['Sku', 'Product', 'Sensation_Posizione', 'Sensation_Prezzo', 'Gap %', 'Indice Comp.', 'AI_Category']],
        use_container_width=True, hide_index=True,
        column_config={
            "Gap %": st.column_config.NumberColumn("Gap %", format="%+.1f%%"),
            "Indice Comp.": st.column_config.ProgressColumn("Indice Comp.", format="%.0f", min_value=80, max_value=150),
            "AI_Category": st.column_config.TextColumn("🏷️ Classificazione AI")
        }
    )

# --- TAB 2: FOCUS PRODOTTO ---
with tab2:
    st.subheader("🔍 Focus Prodotto & Analisi Churn AI")
    if not df.empty:
        prod = st.selectbox("Seleziona Prodotto:", sorted(df['Product'].unique()))
        p_data = df[df['Product'] == prod].iloc[0]
        h_data = df_raw[df_raw['Product'] == prod].sort_values('Data_dt')

        c_info, c_ai = st.columns([1, 1])
        with c_info:
            st.markdown(f"""
                <div style='background:#f0f2f6;padding:20px;border-radius:10px;border-left:5px solid #0056b3;'>
                    <h4>{prod}</h4>
                    <hr>
                    <p>Posizione TP: <b>{p_data['Sensation_Posizione']}°</b></p>
                    <p>Prezzo Attuale: <b>{p_data['Sensation_Prezzo']:.2f} €</b></p>
                </div>
            """, unsafe_allow_html=True)
        
        with c_ai:
            if st.button(f"🚀 Genera Strategia & Previsione Churn"):
                with st.spinner("Gemini sta analizzando lo storico..."):
                    prediction = ai_single_item_strategy(h_data, p_data)
                    st.success(f"🤖 **Consiglio AI:** {prediction}")
        
        # Grafico Storico
        st.plotly_chart(px.line(h_data, x='Data', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], 
                                title=f"Trend Storico: {prod}", 
                                color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'}), 
                        use_container_width=True)
    else:
        st.info("Seleziona un brand nella sidebar per iniziare.")

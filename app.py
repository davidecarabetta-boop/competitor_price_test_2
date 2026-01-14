import streamlit as st
import pandas as pd
import plotly.express as px
from google.oauth2.service_account import Credentials
import gspread

# --- CONFIGURAZIONE UI ---
st.set_page_config(page_title="Sensation Perfume Intelligence", layout="wide", page_icon="🧪")

st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stMetric { background-color: #ffffff; border-radius: 10px; padding: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- 1. FUNZIONE DI CARICAMENTO ROBUSTA ---
@st.cache_data(ttl=3600)
def load_data():
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        # Usa i secrets configurati correttamente
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        
        # Apertura foglio tramite URL nei secrets
        sheet = client.open_by_url(st.secrets["google_sheets"]["sheet_url"]).sheet1
        
        # get_all_values() evita l'errore "duplicate headers" di get_all_records()
        raw_data = sheet.get_all_values()
        
        if not raw_data or len(raw_data) < 2:
            return pd.DataFrame()
            
        # Trasformazione in DataFrame usando la prima riga come header
        df = pd.DataFrame(raw_data[1:], columns=raw_data[0])
        
        # Pulizia: rimuove colonne senza nome e spazi bianchi dai nomi colonne
        df = df.loc[:, df.columns != '']
        df.columns = df.columns.str.strip()
        
        return df
    except Exception as e:
        st.error(f"Errore di connessione a Google Sheets: {e}")
        return pd.DataFrame()

# --- 2. LOGICA AI & NORMALIZZAZIONE ---
def apply_ai_insights(df):
    # Convertiamo i prezzi in numeri per i calcoli, gestendo eventuali errori
    df['Sensation_Prezzo'] = pd.to_numeric(df['Sensation_Prezzo'], errors='coerce').fillna(0)
    df['Comp_1_Prezzo'] = pd.to_numeric(df['Comp_1_Prezzo'], errors='coerce').fillna(0)
    df['Sensation_Posizione'] = pd.to_numeric(df['Sensation_Posizione'], errors='coerce').fillna(0)

    # Rilevamento Anomalie: se il prezzo è > 20% rispetto al minimo [cite: 16, 70]
    df['Anomaly'] = df.apply(lambda x: "⚠️ Overpriced" if x['Sensation_Prezzo'] > (x['Comp_1_Prezzo'] * 1.2) and x['Comp_1_Prezzo'] > 0 else "✅ Ok", axis=1)
    
    # Ottimizzazione: suggerisce il prezzo per essere Rank 1 [cite: 74, 134]
    df['AI_Suggested_Price'] = df.apply(lambda x: x['Comp_1_Prezzo'] - 0.10 if x['Sensation_Posizione'] > 1 and x['Comp_1_Prezzo'] > 0 else x['Sensation_Prezzo'], axis=1)
    
    return df

# --- 3. ESECUZIONE E VALIDAZIONE ---
df_raw = load_data()

# CONTROLLO PRESENZA DATI
if df_raw.empty:
    st.warning("🕵️ Il database sembra vuoto. Verifica che lo script di sincronizzazione sia stato eseguito.")
    st.stop()

# VALIDAZIONE COLONNE CRITICHE (Previene l'errore 'Sensation_Prezzo')
colonne_necessarie = ['Sensation_Prezzo', 'Sensation_Posizione', 'Product', 'Comp_1_Prezzo']
colonne_mancanti = [col for col in colonne_necessarie if col not in df_raw.columns]

if colonne_mancanti:
    st.error(f"⚠️ Errore di struttura nel foglio Google!")
    st.write(f"Mancano le colonne: **{', '.join(colonne_mancanti)}**")
    st.info("Rinomina le colonne nel foglio Google o controlla lo script di sincronizzazione.")
    st.stop()

# Se passiamo la validazione, applichiamo l'AI
df = apply_ai_insights(df_raw)

# --- 4. MAIN DASHBOARD ---
st.title("🧪 Sensation Perfume Pricing Intelligence")
st.markdown("Monitoraggio competitivo via Alphaposition Premium [cite: 13, 14]")

# ROW 1: KPI
col1, col2, col3, col4 = st.columns(4)
win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / df.shape[0]) * 100
avg_pos = df['Sensation_Posizione'].mean()
critical_items = df[df['Anomaly'] == "⚠️ Overpriced"].shape[0]

col1.metric("Buy Box Win Rate", f"{win_rate:.1f}%", help="Percentuale prodotti in posizione 1 [cite: 74]")
col2.metric("Posizione Media", f"{avg_pos:.1f}")
col3.metric("Prodotti Overpriced", critical_items)
col4.metric("Catalogo Monitorato", df.shape[0])

st.divider()

# ROW 2: GRAFICI
c1, c2 = st.columns([2, 1])
with c1:
    st.subheader("Sensation vs Miglior Competitor [cite: 16, 70]")
    fig = px.bar(df.head(15), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'],
                 barmode='group', color_discrete_sequence=['#1f77b4', '#ff7f0e'])
    st.plotly_chart(fig, use_container_width=True)

with c2:
    st.subheader("Distribuzione Rank [cite: 74]")
    fig_pie = px.pie(df, names='Sensation_Posizione', hole=.4)
    st.plotly_chart(fig_pie, use_container_width=True)

# ROW 3: TABELLA DETTAGLIO
st.subheader("📋 Analisi Dettagliata e Suggerimenti AI")
st.dataframe(df[['Product', 'Sensation_Prezzo', 'Comp_1_Prezzo', 'Sensation_Posizione', 'Anomaly', 'AI_Suggested_Price']], 
             use_container_width=True)

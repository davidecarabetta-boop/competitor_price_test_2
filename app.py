import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread

# --- 1. CONFIGURAZIONE UI & LOGO ---
LOGO_PATH = "logosensation.png" 
st.set_page_config(page_title="Sensation Profumerie", layout="wide", page_icon=LOGO_PATH)

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

        # PULIZIA PREZZI (Virgola -> Punto)
        price_cols = ['Sensation_Prezzo', 'Comp_1_Prezzo', 'Comp_2_prezzo']
        for col in price_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace('€', '', regex=False)
                           .str.replace('.', '', regex=False)
                           .str.replace(',', '.', regex=False).str.strip(), 
                    errors='coerce'
                ).fillna(0)
        
        # PULIZIA POSIZIONE (Rank) [cite: 74]
        if 'Sensation_Posizione' in df.columns:
            df['Sensation_Posizione'] = pd.to_numeric(df['Sensation_Posizione'], errors='coerce').fillna(0).astype(int)

        # CONVERSIONE DATA
        df['Data_dt'] = pd.to_datetime(df['Data'], dayfirst=True, errors='coerce')
        return df
    except Exception as e:
        st.error(f"Errore: {e}")
        return pd.DataFrame()

df_raw = load_data()

# --- 3. SIDEBAR (USA TUTTI I BRAND DEL DATABASE) ---
with st.sidebar:
    try: st.image(LOGO_PATH, use_container_width=True)
    except: st.info("Logo non trovato")
    
    st.header("🛒 Filtri Catalogo")
    
    # QUI LA MODIFICA: prendiamo i brand da df_raw per vederli tutti
    full_brand_list = sorted(df_raw['Product'].str.split().str[0].unique()) if not df_raw.empty else []
    selected_brands = st.multiselect("Seleziona Brand", full_brand_list)
    
    if st.button("🔄 Aggiorna"):
        st.cache_data.clear()
        st.rerun()

# --- 4. LOGICA SNAPSHOT INTELLIGENTE ---
if not df_raw.empty:
    # Ordiniamo per data e teniamo l'ultima voce per ogni SKU
    # Questo garantisce che se un brand non è stato aggiornato oggi, vediamo l'ultimo dato utile
    df_latest = df_raw.sort_values('Data_dt', ascending=True).drop_duplicates('Sku', keep='last').copy()
    
    # Applichiamo il filtro brand sui dati deduplicati
    df = df_latest.copy()
    if selected_brands:
        df = df[df['Product'].str.startswith(tuple(selected_brands))]
else:
    st.stop()

# --- 5. DASHBOARD ---
tab1, tab2 = st.tabs(["📊 Overview Mercato", "🔍 Focus Prodotto"])

with tab1:
    # KPI CALCOLATI CORRETTAMENTE
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / len(df)) * 100 if len(df) > 0 else 0
    
    c1.metric("Buy Box Win Rate", f"{win_rate:.1f}%")
    c2.metric("Posizione Media", f"{df['Sensation_Posizione'].mean():.1f}")
    c3.metric("Prezzo Sensation Medio", f"{df['Sensation_Prezzo'].mean():.2f}€")
    c4.metric("Prodotti Visualizzati", len(df))

    st.divider()
    # Grafici e Tabella (come visti in precedenza)
    col_l, col_r = st.columns([2, 1])
    with col_l:
        st.subheader("Confronto Prezzi")
        fig = px.bar(df.head(15), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'], barmode='group')
        st.plotly_chart(fig, use_container_width=True)
    
    with col_r:
        st.subheader("Distribuzione Rank")
        fig_pie = px.pie(df, names='Sensation_Posizione', hole=0.5)
        st.plotly_chart(fig_pie, use_container_width=True)

    st.subheader("📋 Tabella Riepilogativa")
    st.dataframe(df[['Sku', 'Product', 'Sensation_Posizione', 'Sensation_Prezzo', 'Comp_1_Prezzo']], use_container_width=True)

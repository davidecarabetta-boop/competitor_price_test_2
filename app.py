import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gspread
import os
import json

# --- IMPORT MODULO CUSTOM ---
import utils  # Importa il file utils.py creato sopra

# --- 1. CONFIGURAZIONE ---
st.set_page_config(page_title="Sensation AI Pricing Tower", layout="wide", page_icon="🗼")

# Check Secrets
if "gcp_service_account" not in st.secrets or "gemini_api_key" not in st.secrets:
    st.error("⛔ Configurazione mancante in .streamlit/secrets.toml")
    st.stop()

# --- 2. GESTIONE DATI (LOADER) ---
@st.cache_data(ttl=600)
def load_data():
    try:
        # Connessione Google Sheets
        creds_dict = dict(st.secrets["gcp_service_account"])
        client = gspread.service_account_from_dict(creds_dict)
        sh = client.open_by_url(st.secrets["google_sheets"]["sheet_url"])
        
        # A. Caricamento Dati Prezzi
        # Se i dati sono "collassati" in una cella o testo raw, usiamo il parser avanzato
        # Altrimenti leggiamo il foglio standard
        worksheet = sh.sheet1
        raw_records = worksheet.get_all_records()
        df_p = pd.DataFrame(raw_records)
        
        # B. Caricamento Entrate
        try: 
            df_r = pd.DataFrame(sh.worksheet("Entrate").get_all_records())
        except: 
            df_r = pd.DataFrame(columns=['Sku', 'Entrate', 'Vendite'])

        if df_p.empty: return pd.DataFrame()

        # MAPPING COLONNE (Adattivo)
        rename_map = {
            'Sensation_Prezzo': 'Price',
            'Sensation_Posizione': 'Rank',
            'Codice': 'Sku', 'id': 'Sku',
            'Nome Prodotto': 'Product'
        }
        df_p.rename(columns=rename_map, inplace=True)
        
        # C. Pulizia Dati (Usa le funzioni di utils.py)
        # Se mancano colonne chiave, le creiamo
        cols_needed = ['Price', 'Comp_1_Prezzo', 'Rank', 'Sku']
        for c in cols_needed:
            if c not in df_p.columns: df_p[c] = 0

        # Pulizia Valute
        df_p['Price'] = df_p['Price'].apply(utils.clean_currency)
        df_p['Comp_1_Prezzo'] = df_p['Comp_1_Prezzo'].apply(utils.clean_currency)
        
        # Pulizia Entrate
        if not df_r.empty:
            for col in ['Entrate', 'Vendite']:
                if col in df_r.columns: df_r[col] = df_r[col].apply(utils.clean_currency)
            # Standardizza SKU a stringa per il merge
            df_r['Sku'] = df_r['Sku'].astype(str).str.strip()
            df_p['Sku'] = df_p['Sku'].astype(str).str.strip()
            
            # MERGE
            df_final = df_p.merge(df_r, on='Sku', how='left').fillna(0)
        else:
            df_final = df_p
            df_final['Entrate'] = 0
            df_final['Vendite'] = 0

        # D. Gestione Date
        col_data = next((c for c in ['Data', 'Data_esecuzione', 'Date'] if c in df_final.columns), None)
        if col_data:
            df_final['Data_dt'] = pd.to_datetime(df_final[col_data], dayfirst=True, errors='coerce')
        else:
            df_final['Data_dt'] = pd.Timestamp.now()
        
        df_final['Data_dt'] = df_final['Data_dt'].dt.normalize()
        
        # E. Categoria Fallback
        if 'Categoria' not in df_final.columns:
            df_final['Categoria'] = 'Generale'

        return df_final.dropna(subset=['Data_dt'])

    except Exception as e:
        st.error(f"Errore caricamento dati: {e}")
        return pd.DataFrame()

# --- 3. UI DASHBOARD ---
df_raw = load_data()

if df_raw.empty:
    st.warning("⚠️ Nessun dato caricato. Controlla il Google Sheet.")
    st.stop()

with st.sidebar:
    st.title("Sensation AI 🗼")
    st.markdown("---")
    
    # Filtri Temporali
    dates = sorted(df_raw['Data_dt'].dropna().unique())
    if len(dates) > 0:
        min_d, max_d = dates[0], dates[-1]
        # Default all'ultima data disponibile
        start_date, end_date = st.date_input("Periodo Analisi", [min_d, max_d])
    else:
        st.error("Date non valide nel dataset")
        st.stop()
        
    # Applicazione Filtro Data
    mask_date = (df_raw['Data_dt'].dt.date >= start_date) & (df_raw['Data_dt'].dt.date <= end_date)
    df_period = df_raw[mask_date].copy()
    
    # Snapshot Ultimo giorno per i filtri attuali
    df_latest = df_period.sort_values('Data_dt').drop_duplicates('Sku', keep='last').copy()
    
    # Filtri Categoria e Brand
    brands = sorted(list(set([str(p).split()[0] for p in df_latest['Product'] if p])))
    sel_brands = st.multiselect("Brand", brands)
    
    cats = sorted(df_latest['Categoria'].astype(str).unique())
    sel_cats = st.multiselect("Categoria", cats)
    
    # Filtro Dinamico Dati
    df_filtered = df_latest.copy()
    if sel_brands:
        pattern = '|'.join(sel_brands)
        df_filtered = df_filtered[df_filtered['Product'].str.contains(pattern, case=False, na=False)]
    if sel_cats:
        df_filtered = df_filtered[df_filtered['Categoria'].isin(sel_cats)]

    st.markdown("---")
    
    # Pulsante AI
    if "ai_clusters" not in st.session_state: st.session_state.ai_clusters = pd.DataFrame()
    if st.button("✨ Genera Cluster Strategici"):
        with st.spinner("Gemini sta analizzando il mercato..."):
            st.session_state.ai_clusters = utils.ai_clustering_bulk(df_filtered, st.secrets["gemini_api_key"])
            
    if st.button("🗑️ Pulisci Cache"):
        st.cache_data.clear()
        st.rerun()

# --- LAYOUT PRINCIPALE ---
st.header("Control Tower Pricing & Revenue")

# KPI ROW
c1, c2, c3, c4 = st.columns(4)
avg_pos = df_filtered['Rank'].mean()
tot_rev = df_filtered['Entrate'].sum()
price_gap = (df_filtered['Price'] - df_filtered['Comp_1_Prezzo']).mean()

c1.metric("SKU Monitorati", len(df_filtered))
c2.metric("Posizione Media", f"{avg_pos:.1f}", delta_color="inverse")
c3.metric("Entrate Periodo", f"€ {tot_rev:,.0f}")
c4.metric("Gap Medio vs Competitor", f"€ {price_gap:.2f}", help="Se positivo, siamo più cari del best competitor")

# TABS
tab1, tab2 = st.tabs(["📊 Analisi Strategica", "🔮 AI & Dettaglio"])

with tab1:
    col_chart, col_data = st.columns([2, 1])
    
    with col_chart:
        st.subheader("Top 20 SKU per Entrate: Prezzo vs Competitor")
        df_top = df_filtered.sort_values('Entrate', ascending=False).head(20)
        
        if not df_top.empty:
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=df_top['Product'], y=df_top['Price'],
                name='Nostro Prezzo', marker_color='#0056b3'
            ))
            fig.add_trace(go.Bar(
                x=df_top['Product'], y=df_top['Comp_1_Prezzo'],
                name='Miglior Competitor', marker_color='#ff9f43'
            ))
            fig.update_layout(barmode='group', height=500, xaxis_tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nessun dato per il grafico.")

    with col_data:
        st.subheader("Cluster AI")
        if not st.session_state.ai_clusters.empty:
            # Merge risultati AI
            df_ai_view = df_top.merge(st.session_state.ai_clusters, on='Sku', how='left')
            st.dataframe(
                df_ai_view[['Product', 'Cluster', 'Entrate']], 
                hide_index=True, 
                use_container_width=True
            )
        else:
            st.info("Clicca 'Genera Cluster Strategici' nella sidebar per attivare l'AI.")

with tab2:
    st.subheader("Deep Dive Prodotto")
    prods = df_filtered['Product'].unique()
    sel_prod = st.selectbox("Seleziona SKU", prods)
    
    if sel_prod:
        # Recupera dati storici e attuali
        row_now = df_filtered[df_filtered['Product'] == sel_prod].iloc[0]
        df_hist = df_period[df_period['Product'] == sel_prod].sort_values('Data_dt')
        
        c_kpi, c_graph = st.columns([1, 2])
        
        with c_kpi:
            st.markdown(f"### {sel_prod}")
            st.markdown(f"**Prezzo Attuale:** € {row_now['Price']}")
            st.markdown(f"**Competitor:** € {row_now['Comp_1_Prezzo']}")
            
            if st.button("🧠 Chiedi strategia a Gemini"):
                with st.spinner("Elaborazione strategia..."):
                    strategy_json = utils.ai_strategic_analysis(row_now, st.secrets["gemini_api_key"])
                    strat_dict = json.loads(strategy_json)
                    
                    st.success(f"Strategia: {strat_dict.get('strategia', 'N/A')}")
                    st.info(f"Consiglio: {strat_dict.get('motivo', 'N/A')}")
                    if 'prezzo_consigliato' in strat_dict:
                        st.metric("Prezzo Target AI", f"€ {strat_dict['prezzo_consigliato']}")

        with c_graph:
            if not df_hist.empty:
                fig_hist = make_subplots(specs=[[{"secondary_y": True}]])
                
                # Prezzi
                fig_hist.add_trace(go.Scatter(
                    x=df_hist['Data_dt'], y=df_hist['Price'], 
                    name="Noi", mode='lines+markers', line=dict(color='blue')
                ), secondary_y=False)
                
                fig_hist.add_trace(go.Scatter(
                    x=df_hist['Data_dt'], y=df_hist['Comp_1_Prezzo'], 
                    name="Competitor", mode='lines', line=dict(color='orange', dash='dash')
                ), secondary_y=False)
                
                # Entrate (Area)
                fig_hist.add_trace(go.Scatter(
                    x=df_hist['Data_dt'], y=df_hist['Entrate'],
                    name="Entrate", fill='tozeroy', line=dict(width=0, color='rgba(0, 255, 0, 0.2)')
                ), secondary_y=True)
                
                fig_hist.update_layout(title="Trend Prezzo vs Entrate", hovermode="x unified")
                st.plotly_chart(fig_hist, use_container_width=True)

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread
import base64

# --- CONFIGURAZIONE LOGO & UI ---
# Specifichiamo il percorso del file immagine
LOGO_PATH = "logo-sensation.png" 

st.set_page_config(
    page_title="Sensation Perfume Intelligence", 
    layout="wide", 
    page_icon=LOGO_PATH # Ora usa il file come icona della tab del browser
)

# ... caricamento dati e logica ...

# --- 2. SIDEBAR CON IMMAGINE ---
with st.sidebar:
    # Carica l'immagine dal file locale
    # 'use_container_width=True' adatta l'immagine alla larghezza della sidebar
    st.image(LOGO_PATH, use_container_width=True)
    
    st.header("🛒 Filtri Catalogo")
    # ... resto dei filtri ...

# Custom CSS Premium
st.markdown("""
    <style>
    .stSidebar { background-color: #f8f9fa; border-right: 1px solid #eee; }
    .product-card { 
        background-color: white; 
        padding: 24px; 
        border-radius: 12px; 
        border-left: 5px solid #0056b3;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    .metric-container { background-color: #ffffff; border-radius: 10px; padding: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- 1. CARICAMENTO DATI (DB GOOGLE SHEETS) ---
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
        
        # Conversione Numerica con i nuovi nomi colonna forniti
        numeric_cols = ['Sensation_Prezzo', 'Sensation_Posizione', 'Comp_1_Prezzo', 'Comp_2_prezzo']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].replace('[\€,]', '', regex=True).replace('', '0'), errors='coerce').fillna(0)
        
        return df
    except Exception as e:
        st.error(f"Errore caricamento database: {e}")
        return pd.DataFrame()

df_raw = load_data()

# --- 2. SIDEBAR CON LOGO SVG ---
with st.sidebar:
    # Soluzione per l'immagine che non carica: HTML diretto
    st.markdown(f'<div style="text-align: center; padding-bottom: 20px;">{SENSATION_LOGO_SVG}</div>', unsafe_allow_html=True)
    st.header("🛒 Filtri Catalogo")
    
    brand_list = sorted(df_raw['Product'].str.split().str[0].unique()) if not df_raw.empty else []
    selected_brands = st.multiselect("Seleziona Brand", brand_list)
    
    st.divider()
    if st.button("🔄 Sincronizza ora"):
        st.cache_data.clear()
        st.rerun()

# --- 3. VALIDAZIONE ---
if df_raw.empty:
    st.warning("In attesa di dati dal servizio Alphaposition Premium...")
    st.stop()

df = df_raw.copy()
if selected_brands:
    df = df[df['Product'].str.startswith(tuple(selected_brands))]

# --- 4. DASHBOARD INTERATTIVA ---
tab1, tab2 = st.tabs(["📊 Analisi di Mercato", "🔍 Focus Prodotto"])

with tab1:
    # Analisi del posizionamento e prezzi competitivi
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / df.shape[0]) * 100 if not df.empty else 0
    c1.metric("Buy Box Win Rate", f"{win_rate:.1f}%")
    c2.metric("Posizione Media", f"{df['Sensation_Posizione'].mean():.1f}")
    c3.metric("Prezzo Sensation Medio", f"{df['Sensation_Prezzo'].mean():.2f}€")
    c4.metric("SKU Monitorati", len(df))

    col_left, col_right = st.columns([2, 1])
    with col_left:
        st.subheader("Confronto Prezzi: Noi vs Competitor Rank 1")
        fig_bar = px.bar(df.head(15), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'],
                         labels={'value': 'Euro (€)', 'variable': 'Venditore'},
                         barmode='group', color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'})
        st.plotly_chart(fig_bar, use_container_width=True)
        
    with col_right:
        st.subheader("Distribuzione Posizioni (Rank)")
        fig_donut = px.pie(df, names='Sensation_Posizione', hole=0.5, 
                           color_discrete_sequence=px.colors.qualitative.Safe)
        st.plotly_chart(fig_donut, use_container_width=True)

with tab2:
    st.subheader("Analisi Storica e Competitor")
    product_selected = st.selectbox("Seleziona Profumo:", df['Product'].unique())
    
    p_data = df[df['Product'] == product_selected].iloc[0]
    hist_data = df_raw[df_raw['Product'] == product_selected].sort_values('Data')

    col_card, col_chart = st.columns([1, 2])
    
    with col_card:
        # Visualizzazione dettagliata dell'offerta corrente
        st.markdown(f"""
            <div class="product-card">
                <h4 style="margin-top:0;">{product_selected}</h4>
                <p><b>SKU:</b> {p_data['Sku']}</p>
                <p><b>Posizione Attuale:</b> {p_data['Sensation_Posizione']:.0f}°</p>
                <hr>
                <h2 style="color: #0056b3; margin-bottom:0;">{p_data['Sensation_Prezzo']:.2f} €</h2>
                <small>Prezzo di vendita rilevato</small>
            </div>
        """, unsafe_allow_html=True)
        
    with col_chart:
        # Monitoraggio del posizionamento storico
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Sensation_Prezzo'], name='Sensation', line=dict(color='#0056b3', width=4)))
        fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Comp_1_Prezzo'], name=f"Rank 1: {p_data['Comp_rank_1']}", line=dict(dash='dash', color='#ffa500')))
        fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Comp_2_prezzo'], name=f"Rank 2: {p_data['Comp_rank_2']}", line=dict(dash='dot', color='#d62728')))
        
        fig_trend.update_layout(title="Trend Storico Prezzi (€)", hovermode="x unified")
        st.plotly_chart(fig_trend, use_container_width=True)

    # Tabella dettagliata dei competitor rilevati
    st.subheader("Benchmark Competitor Diretti")
    comp_table = pd.DataFrame({
        "Posizione": ["1°", "2°"],
        "Merchant": [p_data['Comp_rank_1'], p_data['Comp_rank_2']],
        "Prezzo Offerto": [f"{p_data['Comp_1_Prezzo']:.2f} €", f"{p_data['Comp_2_prezzo']:.2f} €"]
    })
    st.table(comp_table)

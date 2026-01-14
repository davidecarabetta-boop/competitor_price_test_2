import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread

# --- 1. CONFIGURAZIONE LOGO & UI ---
LOGO_PATH = "logo-sensation.png" 

st.set_page_config(
    page_title="Sensation Profumerie", 
    layout="wide", 
    page_icon=LOGO_PATH
)

# Custom CSS per rifinire l'interfaccia (Mix delle due UI fornite)
st.markdown("""
    <style>
    .stSidebar { background-color: #f8f9fa; border-right: 1px solid #eee; }
    .product-card { 
        background-color: white; 
        padding: 24px; 
        border-radius: 12px; 
        border-left: 5px solid #0056b3;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }
    .stMetric { background-color: #ffffff; border-radius: 10px; padding: 15px; border: 1px solid #f0f0f0; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. CARICAMENTO DATI (DB GOOGLE SHEETS) ---
@st.cache_data(ttl=600)
def load_data():
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_url(st.secrets["google_sheets"]["sheet_url"]).sheet1
        raw_data = sheet.get_all_values()
        
        if not raw_data: return pd.DataFrame()
        
        # Mapping colonne: Data, Product, Sku, Sensation_Posizione, Sensation_Prezzo, 
        # Comp_rank_1, Comp_1_Prezzo, Comp_rank_2, Comp_2_prezzo
        df = pd.DataFrame(raw_data[1:], columns=raw_data[0])
        df.columns = df.columns.str.strip()
        
        # Pulizia e conversione numerica
        numeric_cols = ['Sensation_Prezzo', 'Sensation_Posizione', 'Comp_1_Prezzo', 'Comp_2_prezzo']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].replace('[\€,]', '', regex=True).replace('', '0'), errors='coerce').fillna(0)
        
        return df
    except Exception as e:
        st.error(f"Errore caricamento database: {e}")
        return pd.DataFrame()

df_raw = load_data()

# --- 3. SIDEBAR ---
with st.sidebar:
    # Caricamento immagine locale
    try:
        st.image(LOGO_PATH, use_container_width=True)
    except:
        st.warning("Immagine 'logo-sensation.png' non trovata. Caricala nella cartella principale.")
    
    st.header("🛒 Filtri Catalogo")
    
    # Filtro Brand (estratto dal primo termine del nome prodotto)
    brand_list = sorted(df_raw['Product'].str.split().str[0].unique()) if not df_raw.empty else []
    selected_brands = st.multiselect("Filtra per Brand", brand_list)
    
    st.divider()
    if st.button("🔄 Aggiorna Dati GSheet"):
        st.cache_data.clear()
        st.rerun()

# --- 4. VALIDAZIONE E LOGICA ---
if df_raw.empty:
    st.warning("In attesa di dati dalla sincronizzazione Alphaposition Premium... [cite: 13]")
    st.stop()

df = df_raw.copy()
if selected_brands:
    df = df[df['Product'].str.startswith(tuple(selected_brands))]

# --- 5. DASHBOARD (TABS) ---
tab1, tab2 = st.tabs(["📊 Overview Mercato", "🔍 Focus Prodotto"])

with tab1:
    # KPI - Integrazione Buy Box Win Rate basata sulla posizione delle offerte 
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / df.shape[0]) * 100 if len(df) > 0 else 0
    c1.metric("Buy Box Win Rate", f"{win_rate:.1f}%", help="Percentuale prodotti con Rank 1 ")
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
        fig_donut = px.pie(df, names='Sensation_Posizione', hole=0.5)
        st.plotly_chart(fig_donut, use_container_width=True)

with tab2:
    st.subheader("Analisi Storica e Competitor")
    product_selected = st.selectbox("Seleziona Profumo:", df['Product'].unique())
    
    p_data = df[df['Product'] == product_selected].iloc[0]
    hist_data = df_raw[df_raw['Product'] == product_selected].sort_values('Data')

    col_card, col_chart = st.columns([1, 2])
    
    with col_card:
        # Scheda Prodotto (Dalla seconda interfaccia)
        st.markdown(f"""
            <div class="product-card">
                <h4 style="margin-top:0;">{product_selected}</h4>
                <p><b>SKU:</b> {p_data['Sku']}</p>
                <p><b>Posizione Attuale:</b> {p_data['Sensation_Posizione']:.0f}° </p>
                <hr>
                <h2 style="color: #0056b3; margin-bottom:0;">{p_data['Sensation_Prezzo']:.2f} €</h2>
                <p style="color: green; font-weight: bold;">In Stock</p>
            </div>
        """, unsafe_allow_html=True)
        
    with col_chart:
        # Monitoraggio storico dei prezzi e posizionamento [cite: 15, 16]
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Sensation_Prezzo'], name='Sensation', line=dict(color='#0056b3', width=4)))
        fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Comp_1_Prezzo'], name=f"1°: {p_data['Comp_rank_1']}", line=dict(dash='dash', color='#ffa500')))
        fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Comp_2_prezzo'], name=f"2°: {p_data['Comp_rank_2']}", line=dict(dash='dot', color='#d62728')))
        
        fig_trend.update_layout(title="Andamento Storico Prezzi (€) [cite: 16]", hovermode="x unified")
        st.plotly_chart(fig_trend, use_container_width=True)

    # Dettaglio posizionamento dei competitor rilevati dall'API [cite: 87, 88]
    st.subheader("Benchmark Competitor Diretti")
    comp_table = pd.DataFrame({
        "Posizione": ["1°", "2°"],
        "Merchant": [p_data['Comp_rank_1'], p_data['Comp_rank_2']],
        "Prezzo": [f"{p_data['Comp_1_Prezzo']:.2f} €", f"{p_data['Comp_2_prezzo']:.2f} €"]
    })
    st.table(comp_table)

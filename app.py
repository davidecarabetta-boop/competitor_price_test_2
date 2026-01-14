import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread

# --- CONFIGURAZIONE UI ---
st.set_page_config(page_title="Sensation Perfume Intelligence", layout="wide", page_icon="🧪")

# Custom CSS per Sidebar e Card
st.markdown("""
    <style>
    .stSidebar { background-color: #f8f9fa; }
    .product-card { background-color: white; padding: 20px; border-radius: 10px; border: 1px solid #e0e0e0; }
    .metric-container { background-color: #ffffff; border-radius: 10px; padding: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    </style>
    """, unsafe_allow_html=True)

# --- 1. CARICAMENTO DATI ---
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
        
        # Conversione Numerica secondo i tuoi nuovi nomi colonna
        numeric_cols = ['Sensation_Prezzo', 'Sensation_Posizione', 'Comp_1_Prezzo', 'Comp_2_prezzo']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].replace('[\€,]', '', regex=True).replace('', '0'), errors='coerce').fillna(0)
        
        return df
    except Exception as e:
        st.error(f"Errore caricamento: {e}")
        return pd.DataFrame()

df_raw = load_data()

# --- 2. SIDEBAR (FILTRI & AGGIORNAMENTO) ---
with st.sidebar:
    st.image("https://www.sensationprofumerie.it/logo.png", width=200) # Placeholder logo
    st.header("Filtri Avanzati")
    
    # Simuliamo Categoria e Brand se non presenti esplicitamente nel DB per ora
    brand_list = sorted(df_raw['Product'].str.split().str[0].unique()) if not df_raw.empty else []
    selected_brands = st.multiselect("Filtra per Brand", brand_list)
    
    st.divider()
    if st.button("🔄 Aggiorna Dati GSheet"):
        st.cache_data.clear()
        st.rerun()

# --- 3. VALIDAZIONE E FILTRO ---
if df_raw.empty:
    st.warning("Database vuoto o non raggiungibile.")
    st.stop()

# Filtriamo i dati in base alla sidebar
df = df_raw.copy()
if selected_brands:
    df = df[df['Product'].str.startswith(tuple(selected_brands))]

# --- 4. DASHBOARD PRINCIPALE (MIX INTERFACCE) ---
tab1, tab2 = st.tabs(["📊 Overview Mercato", "🔍 Analisi Singolo Prodotto"])

with tab1:
    # KPI iniziali
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / df.shape[0]) * 100 if not df.empty else 0
    c1.metric("Win Rate", f"{win_rate:.1f}%")
    c2.metric("Posizione Media", f"{df['Sensation_Posizione'].mean():.1f}")
    c3.metric("Prezzo Medio", f"{df['Sensation_Prezzo'].mean():.2f}€")
    c4.metric("Prodotti", len(df))

    # Grafici Globali (dalla prima interfaccia)
    col_left, col_right = st.columns([2, 1])
    with col_left:
        st.subheader("Sensation vs Miglior Competitor")
        fig_bar = px.bar(df.head(15), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'],
                         barmode='group', color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'})
        st.plotly_chart(fig_bar, use_container_width=True)
        
    with col_right:
        st.subheader("Distribuzione Rank")
        fig_donut = px.pie(df, names='Sensation_Posizione', hole=0.5, 
                           color_discrete_sequence=px.colors.qualitative.Pastel)
        st.plotly_chart(fig_donut, use_container_width=True)

with tab2:
    # Sezione Dettaglio (dalla seconda interfaccia)
    st.subheader("Deep Dive Prodotto")
    product_selected = st.selectbox("Seleziona un profumo per l'analisi storica:", df['Product'].unique())
    
    p_data = df[df['Product'] == product_selected].iloc[0]
    hist_data = df_raw[df_raw['Product'] == product_selected].sort_values('Data')

    col_card, col_chart = st.columns([1, 2])
    
    with col_card:
        st.markdown(f"""
            <div class="product-card">
                <h3>Dettagli Prodotto</h3>
                <p><b>SKU:</b> {p_data['Sku']}</p>
                <p><b>Posizione:</b> {p_data['Sensation_Posizione']:.0f}°</p>
                <hr>
                <h2 style="color: #0056b3;">{p_data['Sensation_Prezzo']:.2f} €</h2>
                <p style="color: green;">In Stock</p>
            </div>
        """, unsafe_allow_html=True)
        
    with col_chart:
        # Trend Storico Prezzi
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Sensation_Prezzo'], name='Sensation (Noi)', line=dict(color='#0056b3', width=3)))
        fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Comp_1_Prezzo'], name=p_data['Comp_rank_1'], line=dict(dash='dash', color='#ffa500')))
        fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Comp_2_prezzo'], name=p_data['Comp_rank_2'], line=dict(dash='dot', color='#d62728')))
        
        fig_trend.update_layout(title="Andamento Storico Prezzi (€)", xaxis_title="Data", yaxis_title="Prezzo")
        st.plotly_chart(fig_trend, use_container_width=True)

    # Tabella Competitor (Parte bassa della seconda interfaccia)
    st.subheader("Posizionamento Prezzi Competitor")
    comp_table = pd.DataFrame({
        "Merchant": [p_data['Comp_rank_1'], p_data['Comp_rank_2']],
        "Prezzo": [p_data['Comp_1_Prezzo'], p_data['Comp_2_prezzo']],
        "Rank": [1, 2]
    })
    st.table(comp_table)

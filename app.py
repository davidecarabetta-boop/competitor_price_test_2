import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2.service_account import Credentials
import gspread

# --- 1. CONFIGURAZIONE LOGO & UI ---
LOGO_PATH = "logosensation.png" 

st.set_page_config(
    page_title="Sensation Profumerie", 
    layout="wide", 
    page_icon=LOGO_PATH
)

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

# --- 2. FUNZIONE CARICAMENTO DATI CON PULIZIA VIRGOLE ---
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

        # --- PULIZIA E CONVERSIONE NUMERICA CORRETTA ---
        # 1. Pulizia Prezzi (Sensation_Prezzo, Comp_1_Prezzo, Comp_2_prezzo)
        price_cols = ['Sensation_Prezzo', 'Comp_1_Prezzo', 'Comp_2_prezzo']
        for col in price_cols:
            if col in df.columns:
                # Trasformiamo in stringa, rimuoviamo €, rimuoviamo il punto delle migliaia
                # e infine cambiamo la virgola decimale in punto
                df[col] = pd.to_numeric(
                    df[col].astype(str)
                           .str.replace('€', '', regex=False)
                           .str.replace('.', '', regex=False)  
                           .str.replace(',', '.', regex=False) 
                           .str.strip(), 
                    errors='coerce'
                ).fillna(0)
        
        # 2. Pulizia Posizione (Sensation_Posizione)
        if 'Sensation_Posizione' in df.columns:
            df['Sensation_Posizione'] = pd.to_numeric(
                df['Sensation_Posizione'].astype(str).str.strip(), 
                errors='coerce'
            ).fillna(0).astype(int)

        # 3. Conversione data per snapshotting
        df['Data_dt'] = pd.to_datetime(df['Data'], dayfirst=True, errors='coerce')
        
        return df
    except Exception as e:
        st.error(f"Errore caricamento database: {e}")
        return pd.DataFrame()

df_raw = load_data()

# --- 3. LOGICA SNAPSHOT & SIDEBAR ---
if not df_raw.empty:
    ultima_data = df_raw['Data_dt'].max()
    df_latest = df_raw[df_raw['Data_dt'] == ultima_data].copy()
else:
    st.stop()

with st.sidebar:
    try:
        st.image(LOGO_PATH, use_container_width=True)
    except:
        st.warning("Carica 'logosensation.png' su GitHub")
    
    st.header("🛒 Filtri Catalogo")
    brand_list = sorted(df_latest['Product'].str.split().str[0].unique())
    selected_brands = st.multiselect("Filtra per Brand", brand_list)
    
    st.divider()
    if st.button("🔄 Aggiorna Dati"):
        st.cache_data.clear()
        st.rerun()

df = df_latest.copy()
if selected_brands:
    df = df[df['Product'].str.startswith(tuple(selected_brands))]

# --- 4. DASHBOARD ---
tab1, tab2 = st.tabs(["📊 Overview Mercato", "🔍 Focus Prodotto"])

with tab1:
    # KPI REALI
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df[df['Sensation_Posizione'] == 1].shape[0] / len(df)) * 100 if len(df) > 0 else 0
    
    c1.metric("Buy Box Win Rate", f"{win_rate:.1f}%")
    c2.metric("Posizione Media", f"{df['Sensation_Posizione'].mean():.1f}")
    c3.metric("Prezzo Sensation Medio", f"{df['Sensation_Prezzo'].mean():.2f}€")
    c4.metric("SKU Monitorati", len(df))

    st.divider()

    col_l, col_r = st.columns([2, 1])
    with col_l:
        st.subheader("Confronto Prezzi: Noi vs Miglior Competitor")
        fig_bar = px.bar(df.head(15), x='Product', y=['Sensation_Prezzo', 'Comp_1_Prezzo'],
                         barmode='group', color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'})
        st.plotly_chart(fig_bar, use_container_width=True)
        
    with col_r:
        st.subheader("Distribuzione Rank")
        fig_donut = px.pie(df, names='Sensation_Posizione', hole=0.5)
        st.plotly_chart(fig_donut, use_container_width=True)

    st.divider()
    
    st.subheader(f"📋 Riepilogo Dettagliato Prodotti")
    df_display = df.copy()
    df_display['Gap'] = df_display['Sensation_Prezzo'] - df_display['Comp_1_Prezzo']
    
    st.dataframe(
        df_display[['Sku', 'Product', 'Sensation_Posizione', 'Sensation_Prezzo', 'Comp_1_Prezzo', 'Gap']],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Sensation_Prezzo": st.column_config.NumberColumn("Tuo Prezzo", format="%.2f €"),
            "Comp_1_Prezzo": st.column_config.NumberColumn("Miglior Competitor", format="%.2f €"),
            "Gap": st.column_config.NumberColumn("Gap (€)", format="%.2f €"),
            "Sensation_Posizione": st.column_config.NumberColumn("Rank TP")
        }
    )

with tab2:
    st.subheader("Analisi Storica")
    product_selected = st.selectbox("Seleziona Profumo:", df_latest['Product'].unique())
    p_data = df_latest[df_latest['Product'] == product_selected].iloc[0]
    hist_data = df_raw[df_raw['Product'] == product_selected].sort_values('Data_dt')

    col_card, col_chart = st.columns([1, 2])
    with col_card:
        st.markdown(f"""
            <div class="product-card">
                <h4>{product_selected}</h4>
                <p><b>SKU:</b> {p_data['Sku']}</p>
                <p><b>Posizione Attuale:</b> {p_data['Sensation_Posizione']:.0f}°</p>
                <hr>
                <h2 style="color: #0056b3;">{p_data['Sensation_Prezzo']:.2f} €</h2>
            </div>
        """, unsafe_allow_html=True)
    with col_chart:
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Sensation_Prezzo'], name='Sensation', line=dict(color='#0056b3', width=4)))
        fig_trend.add_trace(go.Scatter(x=hist_data['Data'], y=hist_data['Comp_1_Prezzo'], name=f"1°: {p_data['Comp_rank_1']}", line=dict(dash='dash', color='#ffa500')))
        fig_trend.update_layout(title="Andamento Storico Prezzi (€)", hovermode="x unified")
        st.plotly_chart(fig_trend, use_container_width=True)

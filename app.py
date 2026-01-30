import streamlit as st
import pandas as pd
import plotly.express as px
import google.generativeai as genai
import gspread
import json
import re

# --- 1. CONFIGURAZIONE ---
st.set_page_config(
    page_title="Sensation AI Pricing Tower",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded"
)

if "gcp_service_account" not in st.secrets or "gemini_api_key" not in st.secrets:
    st.error("⛔ Configurazione mancante in secrets.toml")
    st.stop()

genai.configure(api_key=st.secrets["gemini_api_key"])
MODEL_NAME = 'gemini-1.5-flash'

# --- 2. FUNZIONI UTILITÀ ---
def clean_currency(value):
    if pd.isna(value) or str(value).strip() == '': return 0.0
    if isinstance(value, (int, float)): return float(value)
    s = str(value).replace('€', '').replace('$', '').strip()
    try:
        if ',' in s and '.' in s:
            if s.find('.') < s.find(','): s = s.replace('.', '').replace(',', '.')
            else: s = s.replace(',', '')
        elif ',' in s: s = s.replace(',', '.')
        return float(s)
    except: return 0.0

def clean_json_response(text):
    text = text.strip()
    if "```" in text:
        pattern = r"```(?:json)?(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match: text = match.group(1).strip()
    return text

# --- 3. CARICAMENTO DATI ---
@st.cache_data(ttl=600)
def load_data():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        client = gspread.service_account_from_dict(creds_dict)
        sh = client.open_by_url(st.secrets["google_sheets"]["sheet_url"])
        
        # Carica Prezzi
        df_p = pd.DataFrame(sh.sheet1.get_all_records())
        if df_p.empty: return pd.DataFrame(columns=['Sku', 'Product', 'Data_dt', 'Price', 'Rank'])

        # Carica Entrate
        try: df_r = pd.DataFrame(sh.worksheet("Entrate").get_all_records())
        except: df_r = pd.DataFrame(columns=['Sku', 'Entrate', 'Vendite'])

        # MAPPING COLONNE (Il cuore della stabilità)
        rename_map = {
            'Sensation_Prezzo': 'Price',
            'Sensation_Posizione': 'Rank',
            'Codice': 'Sku', 'id': 'Sku'
        }
        df_p.rename(columns=rename_map, inplace=True)

        # Standardizza
        for df in [df_p, df_r]:
            if not df.empty:
                df.columns = df.columns.str.strip()
                if 'Sku' in df.columns: df['Sku'] = df['Sku'].astype(str).str.strip()

        # Check colonne e pulizia
        if 'Price' not in df_p.columns: df_p['Price'] = 0.0
        if 'Rank' not in df_p.columns: df_p['Rank'] = 99
        if 'Comp_1_Prezzo' not in df_p.columns: df_p['Comp_1_Prezzo'] = 0.0
        
        for col in ['Price', 'Comp_1_Prezzo']: df_p[col] = df_p[col].apply(clean_currency)
        df_p['Rank'] = pd.to_numeric(df_p['Rank'], errors='coerce').fillna(99).astype(int)

        if not df_r.empty:
            for col in ['Entrate', 'Vendite']:
                if col in df_r.columns: df_r[col] = df_r[col].apply(clean_currency)

        # Merge
        df_final = df_p.merge(df_r, on='Sku', how='left').fillna(0)
        
        # Data
        col_data = 'Data' if 'Data' in df_final.columns else ('Data_esecuzione' if 'Data_esecuzione' in df_final.columns else None)
        if col_data: df_final['Data_dt'] = pd.to_datetime(df_final[col_data], dayfirst=True, errors='coerce')
        else: df_final['Data_dt'] = pd.Timestamp.now()
            
        return df_final.dropna(subset=['Data_dt'])
    except Exception as e:
        st.error(f"Errore caricamento: {e}")
        return pd.DataFrame()

# --- 4. FUNZIONI AI ---

def ai_clustering_bulk(df_input):
    """Analisi massiva per Tabella"""
    if df_input.empty: return pd.DataFrame()
    df_subset = df_input.sort_values(by='Entrate', ascending=False).head(20)
    cols = ['Sku', 'Product', 'Price', 'Comp_1_Prezzo', 'Rank', 'Entrate']
    for c in cols: 
        if c not in df_subset.columns: df_subset[c] = 0
        
    data_json = df_subset[cols].to_dict(orient='records')
    prompt = f"""
    Analizza: {json.dumps(data_json)}.
    Per ogni SKU definisci Categoria: "Attacco" (Rank>1, gap basso), "Margine" (Rank=1, gap alto), "Monitorare", "Liquidare".
    Output JSON: [{{ "Sku": "...", "Categoria": "..." }}]
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        res = model.generate_content(prompt)
        clean = clean_json_response(res.text)
        return pd.DataFrame(json.loads(clean))
    except: return pd.DataFrame()

def ai_predictive_strategy(hist_data, current_data):
    """Analisi singola per Tab Focus"""
    trend_desc = "Stabile"
    if len(hist_data) > 1:
        start_p = hist_data.iloc[0]['Price']
        end_p = hist_data.iloc[-1]['Price']
        if end_p < start_p: trend_desc = "In discesa"
        elif end_p > start_p: trend_desc = "In salita"

    prompt = f"""
    Analisi Prodotto: {current_data['Product']}
    - Prezzo Nostro: {current_data['Price']}€
    - Competitor: {current_data['Comp_1_Prezzo']}€
    - Posizione: {current_data['Rank']}
    - Trend Storico: {trend_desc}
    
    Il competitor è aggressivo? Conviene abbassare il prezzo o mantenere il margine?
    Rispondi in 3 righe, sii diretto e operativo.
    """
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        res = model.generate_content(prompt)
        return res.text
    except Exception as e: return f"Errore AI: {e}"

# --- 5. UI PRINCIPALE ---

df_raw = load_data()
if df_raw.empty: st.stop()

# Snapshot dati attuali
df_latest = df_raw.sort_values('Data_dt').drop_duplicates('Sku', keep='last').copy()

with st.sidebar:
    st.image("logosensation.png") if "logosensation.png" in st.secrets else st.title("Sensation AI")
    brands = sorted(list(set([str(p).split()[0] for p in df_latest['Product'] if p])))
    sel_brand = st.selectbox("Brand", ["Tutti"] + brands)
    
    st.divider()
    
    # Bottone Cluster nella sidebar che salva in session state
    if "ai_clusters" not in st.session_state:
        st.session_state.ai_clusters = pd.DataFrame()

    if st.button("✨ Genera Clustering AI"):
        with st.spinner("Analisi massiva in corso..."):
            df_in = df_latest if sel_brand == "Tutti" else df_latest[df_latest['Product'].str.startswith(sel_brand)]
            st.session_state.ai_clusters = ai_clustering_bulk(df_in)

# Filtro Dataset
df_view = df_latest.copy()
if sel_brand != "Tutti":
    df_view = df_view[df_view['Product'].str.startswith(sel_brand)]

st.title("🚀 Control Tower Sensation")

# --- DASHBOARD LAYOUT RICHIESTO ---
tab1, tab2 = st.tabs(["📊 Market Intelligence", "🔍 Focus & AI Prediction"])

with tab1:
    # 1. KPI
    # Nota: Usiamo 'Rank' e 'Price' perché li abbiamo rinominati in load_data per stabilità
    c1, c2, c3, c4 = st.columns(4)
    win_rate = (df_view['Rank'] == 1).mean()
    c1.metric("Win Rate", f"{win_rate:.1%}")
    c2.metric("Pos. Media", f"{df_view['Rank'].mean():.1f}")
    c3.metric("Prezzo Medio", f"{df_view['Price'].mean():.2f} €")
    c4.metric("SKU Analizzati", len(df_view))

    st.divider()

    # 2. Grafico Comparativo
    st.subheader("Sensation vs Competitor (Top 10)")
    # Ordiniamo per entrate o per gap prezzo per mostrare i più rilevanti
    df_chart = df_view.sort_values('Entrate', ascending=False).head(10)
    
    # Rinominiamo solo per la visualizzazione del grafico per renderlo chiaro
    df_chart_display = df_chart.rename(columns={'Price': 'Sensation_Prezzo'})
    
    fig_bar = px.bar(
        df_chart_display, 
        x='Product', 
        y=['Sensation_Prezzo', 'Comp_1_Prezzo'], 
        barmode='group', 
        color_discrete_map={'Sensation_Prezzo': '#0056b3', 'Comp_1_Prezzo': '#ffa500'},
        title="Confronto Prezzi Top Seller"
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # 3. Tabella con logica Merge AI
    st.subheader("📋 Piano d'Azione")
    df_display = df_view.copy()
    
    # Se abbiamo risultati AI in memoria, facciamo il merge
    if not st.session_state.ai_clusters.empty:
        df_display = df_display.merge(st.session_state.ai_clusters, on='Sku', how='left')
        df_display['Classificazione AI'] = df_display['Categoria'].fillna("-")
    else:
        df_display['Classificazione AI'] = "Clicca 'Genera Clustering' nella sidebar"

    # Selezione colonne da mostrare
    cols_to_show = ['Sku', 'Product', 'Rank', 'Price', 'Comp_1_Prezzo', 'Classificazione AI', 'Entrate']
    
    # Rinominiamo colonne header per l'utente finale
    df_show = df_display[cols_to_show].rename(columns={
        'Rank': 'Sensation_Posizione',
        'Price': 'Sensation_Prezzo'
    })
    
    st.dataframe(
        df_show.sort_values('Entrate', ascending=False), 
        use_container_width=True, 
        hide_index=True
    )

with tab2:
    st.subheader("🔍 Analisi Predittiva Singolo SKU")
    
    # Selectbox Prodotti
    prod_list = df_view['Product'].unique()
    selected_prod = st.selectbox("Seleziona Prodotto:", prod_list)
    
    if selected_prod:
        # Dati puntuali
        p_data = df_view[df_view['Product'] == selected_prod].iloc[0]
        # Dati storici (dal dataframe raw completo)
        h_data = df_raw[df_raw['Product'] == selected_prod].sort_values('Data_dt')

        col_info, col_ai = st.columns([1, 1])
        with col_info:
            st.info(
                f"**{selected_prod}**\n\n"
                f"💰 Prezzo Attuale: **{p_data['Price']}€**\n\n"
                f"🏆 Posizione: **{p_data['Rank']}°**\n\n"
                f"🆚 Competitor: **{p_data['Comp_1_Prezzo']}€**"
            )
        
        with col_ai:
            if st.button("🚀 Analizza con AI (Deep Dive)"):
                with st.spinner("L'AI sta studiando lo storico..."):
                    analisi = ai_predictive_strategy(h_data, p_data)
                    st.success(f"**Consiglio AI:**\n\n{analisi}")
        
        # Grafico Trend
        
        fig_line = px.line(
            h_data, 
            x='Data_dt', 
            y=['Price', 'Comp_1_Prezzo'], 
            markers=True,
            color_discrete_map={'Price': '#0056b3', 'Comp_1_Prezzo': '#ffa500'},
            title="Trend Storico Prezzi"
        )
        # Rinomina legenda per chiarezza
        new_names = {'Price': 'Sensation', 'Comp_1_Prezzo': 'Competitor'}
        fig_line.for_each_trace(lambda t: t.update(name = new_names[t.name],
                                      legendgroup = new_names[t.name],
                                      hovertemplate = t.hovertemplate.replace(t.name, new_names[t.name])
                                     )
                  )
        
        st.plotly_chart(fig_line, use_container_width=True)

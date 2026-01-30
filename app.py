@st.cache_data(ttl=600)
def load_data():
    try:
        # --- CONNESSIONE GOOGLE SHEETS ---
        scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        client = gspread.authorize(creds)
        
        sh = client.open_by_url(st.secrets["google_sheets"]["sheet_url"])
        
        # 1. CARICAMENTO DATI FOGLIO 1 (PREZZI E DATA)
        data_p = sh.sheet1.get_all_records()
        df_p = pd.DataFrame(data_p)
        
        if df_p.empty:
            return pd.DataFrame(columns=['Sku', 'Product', 'Data_dt', 'Entrate'])

        # 2. CARICAMENTO DATI ENTRATE
        try:
            data_r = sh.worksheet("Entrate").get_all_records()
            df_r = pd.DataFrame(data_r)
        except:
            df_r = pd.DataFrame(columns=['Sku', 'Entrate', 'Vendite'])

        # --- PULIZIA COLONNE (Trim spazi vuoti nei nomi) ---
        for df in [df_p, df_r]:
            if not df.empty:
                df.columns = df.columns.str.strip() 
                if 'Sku' in df.columns:
                    df['Sku'] = df['Sku'].astype(str).str.strip()

        # --- PULIZIA PREZZI ---
        cols_to_clean = [c for c in df_p.columns if any(x in c.lower() for x in ['prezzo', 'price', 'costo'])]
        for col in cols_to_clean:
            df_p[col] = df_p[col].apply(clean_currency)
            
        if 'Rank' in df_p.columns:
            df_p['Rank'] = pd.to_numeric(df_p['Rank'], errors='coerce').fillna(99).astype(int)

        # --- PULIZIA ENTRATE ---
        if not df_r.empty:
            for col in ['Entrate', 'Vendite']:
                if col in df_r.columns:
                    df_r[col] = df_r[col].apply(clean_currency)

        # --- MERGE (UNIONE) ---
        df_final = df_p.merge(df_r, on='Sku', how='left').fillna(0)
        
        # --- FIX DATA (IL PUNTO CRITICO) ---
        # 1. Cerchiamo la colonna "Data" (quella che hai tu)
        # 2. Se non c'è, cerchiamo "Data_Esecuzione" come fallback
        col_data_trovata = None
        
        if 'Data' in df_final.columns:
            col_data_trovata = 'Data'
        elif 'Data_Esecuzione' in df_final.columns:
            col_data_trovata = 'Data_Esecuzione'
            
        if col_data_trovata:
            # Converte la colonna trovata in formato data temporale (Data_dt)
            # dayfirst=True è importante per le date italiane (GG/MM/AAAA)
            df_final['Data_dt'] = pd.to_datetime(df_final[col_data_trovata], dayfirst=True, errors='coerce')
        else:
            # Se manca del tutto la colonna data, usiamo oggi per evitare il crash KeyError
            st.warning("⚠️ Colonna 'Data' non trovata nel foglio! Uso la data odierna.")
            df_final['Data_dt'] = pd.Timestamp.now()

        # Rimuove righe dove la data non è valida (NaT) per evitare errori successivi
        df_final = df_final.dropna(subset=['Data_dt'])

        return df_final

    except Exception as e:
        st.error(f"❌ Errore critico nel caricamento dati: {str(e)}")
        # Ritorna un dataframe vuoto ma con le colonne necessarie per non far esplodere l'app
        return pd.DataFrame(columns=['Sku', 'Data_dt', 'Entrate', 'Product', 'Comp_1_Prezzo', 'Price'])

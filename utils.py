import pandas as pd
import re
import json
import google.generativeai as genai
import streamlit as st

# --- CONFIGURAZIONE AI ---
def configure_genai(api_key):
    genai.configure(api_key=api_key)

# --- PULIZIA DATI ---
def clean_currency(value):
    """Pulisce prezzi sporchi (es. '1.200,50 €' -> 1200.50)"""
    if pd.isna(value) or str(value).strip() == '': return 0.0
    if isinstance(value, (int, float)): return float(value)
    
    # Rimuove simboli valuta e spazi
    s = str(value).replace('€', '').replace('$', '').strip()
    
    try:
        # Gestione formati europei vs americani
        if ',' in s and '.' in s:
            if s.find('.') < s.find(','): # Caso 1.000,00
                s = s.replace('.', '').replace(',', '.')
            else: # Caso 1,000.00
                s = s.replace(',', '')
        elif ',' in s: # Caso 12,50
            s = s.replace(',', '.')
        return float(s)
    except:
        return 0.0

def parse_collapsed_data(raw_data_string):
    """
    Risolve il problema dei dati 'incollati' senza spazi (es. 14/01/202614/01/2025Nome...)
    Restituisce un DataFrame pulito.
    """
    lines = [line.strip() for line in raw_data_string.strip().split('\n') if line.strip()]
    df = pd.DataFrame(lines, columns=['raw_string'])
    
    # REGEX AVANZATA per separare i campi fusi
    # 1. Data Scrape | 2. Data Pricing | 3. Nome Prodotto | 4. ID | 5. Count | 6. Prezzo | 7. Merchant
    regex_pattern = r'^(\d{2}/\d{2}/\d{4})\s*(\d{2}/\d{2}/\d{4})\s*(.+?)(\d{5,})\s*(\d+)\s*(\d+,\d+)\s*(.+)$'
    
    extracted = df['raw_string'].str.extract(regex_pattern)
    
    if extracted.isnull().all().all():
        # Fallback se il formato non è quello 'collassato' ma tabulare sporco
        return pd.DataFrame()

    extracted.columns = ['Data_Scrape', 'Data_Pricing', 'Product', 'Sku', 'Competitors', 'Best_Price', 'Best_Competitor']
    
    # Type Casting
    extracted['Best_Price'] = extracted['Best_Price'].apply(clean_currency)
    extracted['Competitors'] = pd.to_numeric(extracted['Competitors'], errors='coerce').fillna(0).astype(int)
    extracted['Data_Pricing'] = pd.to_datetime(extracted['Data_Pricing'], format='%d/%m/%Y', errors='coerce')
    
    return extracted

def clean_json_response(text):
    """Estrae JSON puro dalla risposta di Gemini"""
    text = text.strip()
    if "```" in text:
        pattern = r"```(?:json)?(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match: text = match.group(1).strip()
    return text

# --- LOGICA AI ---
def ai_strategic_analysis(row, api_key):
    """Analisi puntuale per singolo prodotto"""
    configure_genai(api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    Ruolo: Senior Pricing Manager.
    Prodotto: {row.get('Product', 'N/A')}
    Il nostro prezzo: {row.get('Price', 0)}€
    Miglior Competitor: {row.get('Comp_1_Prezzo', 0)}€
    Posizione attuale: {row.get('Rank', 99)}
    
    Analisi richiesta (rispondi in JSON):
    {{
        "strategia": "Attacco" (se possiamo abbassare) | "Difesa" (se abbiamo margine) | "Allineamento",
        "prezzo_consigliato": (numero float),
        "motivo": (max 10 parole)
    }}
    """
    try:
        res = model.generate_content(prompt)
        return clean_json_response(res.text)
    except Exception as e:
        return json.dumps({"error": str(e)})

def ai_clustering_bulk(df_input, api_key):
    """Clustering su più prodotti contemporaneamente per risparmiare chiamate"""
    if df_input.empty: return pd.DataFrame()
    
    configure_genai(api_key)
    df_subset = df_input.sort_values(by='Entrate', ascending=False).head(15)
    
    # Prepariamo un dataset leggero per il prompt
    cols = ['Sku', 'Product', 'Price', 'Comp_1_Prezzo', 'Rank', 'Entrate']
    # Assicuriamoci che le colonne esistano
    existing_cols = [c for c in cols if c in df_subset.columns]
    data_json = df_subset[existing_cols].to_dict(orient='records')
    
    prompt = f"""
    Analizza questi dati di vendita e pricing: {json.dumps(data_json)}.
    Classifica ogni SKU in una di queste categorie strategiche:
    1. "Cash Cow" (Alto fatturato, buona posizione)
    2. "Battleground" (Alto fatturato, prezzo non competitivo)
    3. "Opportunity" (Basso fatturato, ma prezzo competitivo)
    4. "Dead Stock" (Basso fatturato, prezzo fuori mercato)
    
    Output atteso: JSON Array puro: [{{ "Sku": "...", "Cluster": "..." }}]
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        res = model.generate_content(prompt)
        clean_text = clean_json_response(res.text)
        return pd.DataFrame(json.loads(clean_text))
    except:
        return pd.DataFrame()

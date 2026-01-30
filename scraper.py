import requests
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
import gspread
import os
import json
from gspread_dataframe import set_with_dataframe

# --- CONFIGURAZIONE ---
XML_FEED_URL = "https://feeds.datafeedwatch.com/62653/5de2db28bf341d54bffbab7e2af0711a40c1d189.xml"
MERCHANT_ID = "sensationprofumerie"
# Gestione robusta delle env vars con fallback vuoto per evitare crash immediati
API_KEY = os.environ.get("TP_API_KEY", "") 
SHEET_URL = "https://docs.google.com/spreadsheets/d/1eIojQyXLuC1FO89ZGcswy4s8AgFX3xc1UuheFFgM6Kk/edit#gid=0"
GOOGLE_CREDENTIALS = os.environ.get("GCP_SA_KEY")
BASE_URL = "https://services.7pixel.it/api/v1/"

LIMITE_PRODOTTI = 500 
LIMITE_COMPETITOR = 10

# Sessione globale per riutilizzo connessioni (velocizza le richieste)
session = requests.Session()

def get_xml_ids(url, limit):
    """Scarica XML ed estrae solo gli ID necessari per il filtro."""
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        
        # Parsing leggero
        root = ET.fromstring(response.content)
        
        # Gestione namespace generica e ricerca item/product
        ids = set() # Set per evitare duplicati e lookup O(1)
        
        # Cerca sia item che product (gestione feed Google o generici)
        items = root.findall('.//item') or root.findall('.//product') or root.findall('.//{http://base.google.com/ns/1.0}item')
        
        for item in items:
            # Cerca ID in vari formati comuni
            p_id = (item.findtext('id') or 
                    item.findtext('{http://base.google.com/ns/1.0}id') or 
                    item.findtext('g:id'))
            
            if p_id:
                ids.add(str(p_id).strip())
                if len(ids) >= limit:
                    break
        return list(ids)
    except Exception as e:
        print(f"❌ Errore critico download XML: {e}")
        return []

def expand_competitors(offers_list):
    """Funzione helper per espandere la lista competitor in colonne (da usare con apply)."""
    row_data = {}
    # Assicuriamoci che offers_list sia una lista
    if not isinstance(offers_list, list):
        offers_list = []
        
    for i in range(1, LIMITE_COMPETITOR + 1):
        idx = i - 1
        if idx < len(offers_list):
            row_data[f'Comp_{i}_Nome'] = offers_list[idx].get('Merchant', '-')
            row_data[f'Comp_{i}_Prezzo'] = offers_list[idx].get('Price', 0)
        else:
            row_data[f'Comp_{i}_Nome'] = "-"
            row_data[f'Comp_{i}_Prezzo'] = 0
    return pd.Series(row_data)

def sync_data():
    if not GOOGLE_CREDENTIALS or not API_KEY:
        print("⚠️ Credenziali mancanti (GCP_SA_KEY o TP_API_KEY). Stop.")
        return

    print("🚀 Avvio Sync...")

    # 1. Recupero ID dal Feed (XML)
    xml_ids = get_xml_ids(XML_FEED_URL, LIMITE_PRODOTTI)
    if not xml_ids:
        print("⚠️ Nessun prodotto trovato nel feed XML.")
        return
    print(f"📦 Trovati {len(xml_ids)} ID nel feed XML.")

    try:
        # 2. API Trovaprezzi (Auth + Download)
        # Auth
        url_token = f"{BASE_URL}TemporaryToken"
        r_token = session.get(url_token, params={'merchantid': MERCHANT_ID.lower(), 'merchantkey': API_KEY}, timeout=10)
        token = r_token.json().get("Token")
        
        if not token:
            print("❌ Errore ottenimento Token Trovaprezzi.")
            return

        # Download Ranking
        print("⬇️ Scarico dati ranking Trovaprezzi...")
        url_data = f"{BASE_URL}OffersRanking"
        r_data = session.get(url_data, params={'merchantid': MERCHANT_ID.lower(), 'token': token, 'format': 'json'}, timeout=60)
        raw_tp = r_data.json()
        
        # Creazione DataFrame iniziale
        df_tp = pd.DataFrame(raw_tp)
        if df_tp.empty:
            print("⚠️ Nessun dato ricevuto da Trovaprezzi.")
            return

        # 3. Filtraggio
        # Convertiamo in stringa per match sicuro
        df_tp['Sku'] = df_tp['Sku'].astype(str).str.strip()
        # Filtriamo solo quelli presenti nell'XML
        df_filtrato = df_tp[df_tp['Sku'].isin(xml_ids)].copy()
        
        if df_filtrato.empty:
            print("⚠️ Nessuna corrispondenza tra Feed XML e API Trovaprezzi.")
            return

        print(f"⚡ Elaborazione di {len(df_filtrato)} SKU...")

        # 4. Elaborazione Vettorializzata (No iterrows!)
        
        # A. Espansione Competitor: Applichiamo la funzione una volta sola su tutta la colonna
        # Questo crea un nuovo DF con le colonne Comp_1_Nome, Comp_1_Prezzo, ecc.
        df_competitors = df_filtrato['BestOffers'].apply(expand_competitors)
        
        # B. Unione dei dati
        df_finale = pd.concat([df_filtrato, df_competitors], axis=1)
        
        # C. Pulizia e aggiunta colonne meta
        df_finale['Data_Esecuzione'] = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        # Rinomina colonne per coerenza se necessario o fallback
        if 'MinPrice' in df_finale.columns:
            df_finale.rename(columns={'MinPrice': 'MinPrice_Market'}, inplace=True)
        else:
            df_finale['MinPrice_Market'] = 0

        # Selezione colonne finali pulite (opzionale, per evitare di scrivere BestOffers che è un JSON)
        colonne_da_escludere = ['BestOffers', 'Offers'] # Rimuoviamo colonne nested pesanti
        df_finale.drop(columns=[c for c in colonne_da_escludere if c in df_finale.columns], inplace=True)

        # 5. Scrittura su Google Sheets
        print("☁️ Scrittura su Google Sheets...")
        
        info_chiave = json.loads(GOOGLE_CREDENTIALS)
        gc = gspread.service_account_from_dict(info_chiave)
        sh = gc.open_by_url(SHEET_URL)
        sheet = sh.sheet1
        
        # Ottimizzazione ricerca riga: leggiamo solo la colonna A invece di tutto il foglio
        try:
            col_a = sheet.col_values(1)
            next_row = len(col_a) + 1
        except:
            next_row = 1
            
        # Scrittura
        set_with_dataframe(
            sheet, 
            df_finale, 
            row=next_row, 
            include_column_header=(next_row == 1) # Header solo se il foglio è vuoto
        )
        
        print(f"✅ Sync completato con successo: {len(df_finale)} righe aggiunte.")

    except Exception as e:
        print(f"❌ Errore durante il processo: {e}")
        # Opzionale: stampa traceback completo per debug
        # import traceback
        # traceback.print_exc()

if __name__ == "__main__":
    sync_data()

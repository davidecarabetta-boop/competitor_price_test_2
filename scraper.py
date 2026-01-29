
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
API_KEY = os.environ.get("TP_API_KEY") 
SHEET_URL = "https://docs.google.com/spreadsheets/d/1eIojQyXLuC1FO89ZGcswy4s8AgFX3xc1UuheFFgM6Kk/edit#gid=0"
GOOGLE_CREDENTIALS = os.environ.get("GCP_SA_KEY")
BASE_URL = "https://services.7pixel.it/api/v1/"

LIMITE_PRODOTTI = 500 
LIMITE_COMPETITOR = 10

def get_xml_products(url, limit):
    try:
        response = requests.get(url)
        root = ET.fromstring(response.content)
        products_info = []
        items = root.findall('.//item') or root.findall('.//product')
        for product in items:
            p_id = product.findtext('id') or product.findtext('{http://base.google.com/ns/1.0}id')
            p_title = product.findtext('title') or product.findtext('{http://base.google.com/ns/1.0}title')
            if p_id or p_title:
                products_info.append({'id': str(p_id).strip(), 'title': str(p_title).strip()})
            if len(products_info) >= limit: break
        return products_info
    except Exception as e:
        print(f"❌ Errore XML: {e}")
        return []

def sync_data():
    if not GOOGLE_CREDENTIALS or not API_KEY: return

    # 1. Auth & Token TP
    info_chiave = json.loads(GOOGLE_CREDENTIALS)
    gc = gspread.service_account_from_dict(info_chiave)
    sheet = gc.open_by_url(SHEET_URL).sheet1
    
    url_token = f"{BASE_URL}TemporaryToken?merchantid={MERCHANT_ID.lower()}&merchantkey={API_KEY}"
    token = requests.get(url_token).json().get("Token") # [cite: 217]

    # 2. Download Dati Ranking [cite: 233]
    url_data = f"{BASE_URL}OffersRanking?merchantid={MERCHANT_ID.lower()}&token={token}&format=json"
    raw_tp = requests.get(url_data).json()
    df_tp = pd.DataFrame(raw_tp)

    # 3. Matching & Arricchimento
    prodotti_xml = get_xml_products(XML_FEED_URL, LIMITE_PRODOTTI)
    lista_ids = [p['id'] for p in prodotti_xml]
    df_filtrato = df_tp[df_tp['Sku'].astype(str).isin(lista_ids)].copy()

    # 4. Calcolo KPI di riga
    ora_attuale = datetime.now().strftime("%d/%m/%Y %H:%M")
    df_filtrato['Data_Esecuzione'] = ora_attuale
    
    rows = []
    for _, row in df_filtrato.iterrows():
        dati = row.to_dict()
        offers = dati.get('BestOffers', []) # [cite: 87]
        
        # Mapping competitor
        for i in range(1, LIMITE_COMPETITOR + 1):
            if i <= len(offers):
                dati[f'Comp_{i}_Nome'] = offers[i-1].get('Merchant')
                dati[f'Comp_{i}_Prezzo'] = offers[i-1].get('Price')
            else:
                dati[f'Comp_{i}_Nome'] = "-"
                dati[f'Comp_{i}_Prezzo'] = 0
        
        # Campi extra per dashboard 
        dati['Popularity'] = row.get('Popularity', 0)
        dati['MinPrice_Market'] = row.get('MinPrice', 0)
        rows.append(dati)

    df_finale = pd.DataFrame(rows)
    
    # Scrittura (Append)
    esistenti = sheet.get_all_values()
    set_with_dataframe(sheet, df_finale, row=len(esistenti)+1, include_column_header=(len(esistenti)==0))
    print(f"✅ Sync completato: {len(df_finale)} SKU.")

if __name__ == "__main__":
    sync_data()

import requests
from bs4 import BeautifulSoup
import json
import re
from googletrans import Translator
import time

def clean_name(filename):
    # הסרת סיומות נפוצות
    name = filename.replace('.obf.zip', '').replace('.voice.zip', '').replace('.extra.zip', '')
    # החלפת קו תחתון ברווח (שומר על מקף - כפי שביקשת)
    name = name.replace('_', ' ')
    return name

def translate_text(text, translator):
    # תרגומים ספציפיים כפי שביקשת
    overrides = {
        "israel": "ישראל הקטנה",
        "palestine": "שטחי יש\"ע"
    }
    
    lower_text = text.lower()
    for key, val in overrides.items():
        if key in lower_text:
            return val

    try:
        translated = translator.translate(text, dest='he', src='en')
        return translated.text
    except:
        return text # במקרה של שגיאה יחזיר את האנגלית

def main():
    url = "https://download.osmand.net/list.php"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    translator = Translator()
    
    data_list = []
    rows = soup.find_all('tr')[1:] # דילוג על הכותרת
    
    print(f"Found {len(rows)} files. Starting translation...")

    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 1: continue
        
        link_tag = cells[0].find('a')
        if not link_tag: continue
        
        filename = link_tag.text
        path = link_tag.get('href')
        
        # ניקוי שם הקובץ
        cleaned = clean_name(filename)
        
        # תרגום (הוספנו השהייה קלה כדי לא להיחסם ע"י גוגל)
        translated = translate_text(cleaned, translator)
        time.sleep(0.2) 
        
        data_list.append({
            "he_name": translated,
            "en_name": cleaned,
            "path": path
        })
        
        if len(data_list) % 50 == 0:
            print(f"Translated {len(data_list)} items...")

    # שמירה ל-JSON
    with open('maps_data.json', 'w', encoding='utf-8') as f:
        json.dump(data_list, f, ensure_ascii=False, indent=4)
    
    print("Done! Data saved to maps_data.json")

if __name__ == "__main__":
    main()

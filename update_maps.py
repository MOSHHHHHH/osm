import requests
from bs4 import BeautifulSoup
import json
import os
import re
import google.generativeai as genai

# הגדרת מפתח ה-API
GEMINI_API_KEY = "YOUR_API_KEY_HERE"  # כאן מכניסים את ה-API KEY
genai.configure(api_key=GEMINI_API_KEY)

# שימוש במודל gemini-3.1-flash-lite
model = genai.GenerativeModel('gemini-3.1-flash-lite')

def clean_name(filename):
    # הסרת סיומות קבצים נפוצות של OsmAnd
    name = filename.replace('.obf.zip', '').replace('.voice.zip', '').replace('.extra.zip', '')
    # החלפת קו תחתון ברווח
    name = name.replace('_', ' ')
    # הסרת מספרים (גרסאות/תאריכים)
    name = re.sub(r'\d+', '', name)
    # ניקוי רווחים כפולים
    name = " ".join(name.split())
    return name

def save_json(data):
    with open('maps_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def translate_geographic_name(text):
    # הנחיה מותאמת לתרגום גיאוגרפי מדויק
    prompt = (
        f"You are a professional cartographic translator. "
        f"Translate the following map region or place name into Hebrew. "
        f"Use common Hebrew geographic naming conventions. "
        f"Output ONLY the translated Hebrew name. No explanations, no notes. "
        f"English name: {text}"
    )
    
    response = model.generate_content(prompt)
    return response.text.strip()

def main():
    url = "https://download.osmand.net/list.php"
    
    existing_map = {}
    if os.path.exists('maps_data.json'):
        try:
            with open('maps_data.json', 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                # בניית מילון קיים כדי למנוע תרגום חוזר של מה שכבר תורגם
                existing_map = {item['en_name']: item['he_name'] for item in old_data if item.get('he_name')}
        except:
            print("שגיאה בקריאת הקובץ הקיים, יוצר נתונים מחדש...", flush=True)

    print("מתחבר לאתר OsmAnd לשליפת רשימת הקבצים...", flush=True)
    try:
        response = requests.get(url, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')[1:]
    except Exception as e:
        print(f"שגיאה בתקשורת עם האתר: {e}", flush=True)
        return

    final_data = []
    for row in rows:
        cells = row.find_all('td')
        if not cells: continue
        link_tag = cells[0].find('a')
        if not link_tag: continue
        
        filename = link_tag.text
        path = "https://download.osmand.net" + link_tag.get('href')
        cleaned_en = clean_name(filename)
        he_name = existing_map.get(cleaned_en, "")
        
        final_data.append({
            "he_name": he_name,
            "en_name": cleaned_en,
            "path": path
        })

    print(f"נסרקו {len(final_data)} פריטים. מתחיל תרגום עם Gemini 3.1 Flash-Lite...", flush=True)

    translation_count = 0
    limit = 500 
    
    for i, item in enumerate(final_data):
        # אם כבר יש תרגום, דלג
        if item["he_name"] != "":
            continue
            
        if translation_count >= limit:
            print(f"הגענו למגבלת {limit} תרגומים. עוצרים.", flush=True)
            break

        text_to_translate = item["en_name"].replace('-', ' ')
        lower_name = item["en_name"].lower()

        # לוגיקה מיוחדת למפות ספציפיות
        if "israel" in lower_name:
            translated_he = "ישראל הקטנה"
        elif "palestine" in lower_name:
            translated_he = "שטחי יש\"ע"
        else:
            try:
                print(f"[{i+1}/{len(final_data)}] מתרגם: {text_to_translate}...", end=" ", flush=True)
                translated_he = translate_geographic_name(text_to_translate)
                print(f"תוצאה: {translated_he}", flush=True)
                translation_count += 1
                # ללא time.sleep - שליחה רציפה
            except Exception as e:
                print(f"\nשגיאה ב-API של Gemini: {e}. שומר התקדמות ועוצר.", flush=True)
                break

        item["he_name"] = translated_he
        # שמירה לאחר כל פעולה למניעת אובדן נתונים
        save_json(final_data)

    save_json(final_data)
    print(f"הסתיים! תורגמו {translation_count} פריטים חדשים.", flush=True)

if __name__ == "__main__":
    main()

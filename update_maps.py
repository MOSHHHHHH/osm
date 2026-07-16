print("הפעולה התחילה", flush=True)

import requests
from bs4 import BeautifulSoup
import json
import os
from googletrans import Translator
import time
import re

def clean_name(filename):
    # הסרת סיומות
    name = filename.replace('.obf.zip', '').replace('.voice.zip', '').replace('.extra.zip', '')
    # החלפת קו תחתון ברווח
    name = name.replace('_', ' ')
    # הסרת מספרים (2, 0 וכו')
    name = re.sub(r'\d+', '', name)
    # ניקוי רווחים כפולים שנוצרו
    name = " ".join(name.split())
    return name

def save_json(data):
    with open('maps_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def main():
    url = "https://download.osmand.net/list.php"
    
    # 1. טעינת נתונים קיימים
    existing_map = {}
    if os.path.exists('maps_data.json'):
        try:
            with open('maps_data.json', 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                existing_map = {item['en_name']: item['he_name'] for item in old_data if item.get('he_name')}
        except:
            print("יוצר קובץ JSON חדש...", flush=True)

    # 2. משיכת רשימת הקבצים
    print("מושך נתונים מאתר OsmAnd...", flush=True)
    try:
        response = requests.get(url, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')[1:]
    except Exception as e:
        print(f"שגיאה בתקשורת עם האתר: {e}", flush=True)
        return

    # 3. בניית רשימה ראשונית
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

    save_json(final_data)
    print(f"נסרקו {len(final_data)} קבצים. מתחיל תרגום...", flush=True)

    # 4. לולאת תרגום עם עצירה במקרה של חסימה
    translator = Translator()
    blocked = False
    
    for i, item in enumerate(final_data):
        if item["he_name"] != "":
            continue
            
        if blocked: # אם סומן שנחסמנו, מפסיקים לנסות
            break

        cleaned_en = item["en_name"]
        lower_name = cleaned_en.lower()
        
        # תרגומים קבועים
        if "israel" in lower_name:
            translated_he = "ישראל הקטנה"
        elif "palestine" in lower_name:
            translated_he = "שטחי יש\"ע"
        else:
            try:
                print(f"[{i+1}/{len(final_data)}] מנסה לתרגם: {cleaned_en}...", end=" ", flush=True)
                translated_he = translator.translate(cleaned_en, dest='he', src='en').text
                print(f"הצליח! תורגם ל: {translated_he}", flush=True)
                time.sleep(1.5) # השהייה למניעת חסימה
            except Exception as e:
                print(f"\nנכשל! (ייתכן שנחסמנו ע''י גוגל). שומר תוצאות ועוצר. שגיאה: {e}", flush=True)
                blocked = True
                continue

        item["he_name"] = translated_he
        save_json(final_data) # שמירה אחרי כל תרגום מוצלח

    if blocked:
        print("הפעולה נעצרה באמצע עקב חסימה, אך כל מה שתורגם עד כה נשמר.", flush=True)
    else:
        print("הסתיים בהצלחה! כל הנתונים מעודכנים.", flush=True)

if __name__ == "__main__":
    main()

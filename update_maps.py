print("הפעולה התחילה", flush=True)

import requests
from bs4 import BeautifulSoup
import json
import os
from googletrans import Translator
import time
import sys

def clean_name(filename):
    name = filename.replace('.obf.zip', '').replace('.voice.zip', '').replace('.extra.zip', '')
    name = name.replace('_', ' ')
    return name

def save_json(data):
    with open('maps_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def main():
    url = "https://download.osmand.net/list.php"
    
    # 1. טעינת נתונים קיימים (כדי לא לתרגם מחדש)
    existing_map = {}
    if os.path.exists('maps_data.json'):
        try:
            with open('maps_data.json', 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                existing_map = {item['en_name']: item['he_name'] for item in old_data if item.get('he_name')}
        except:
            print("לא נמצא קובץ קיים תקין, יוצר חדש...", flush=True)

    # 2. משיכת רשימת הקבצים מהאתר
    print("מושך נתונים מאתר OsmAnd...", flush=True)
    try:
        response = requests.get(url, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')[1:]
    except Exception as e:
        print(f"שגיאה במשיכת האתר: {e}", flush=True)
        return

    # 3. יצירת רשימה ראשונית (שלד) ושמירה מיידית
    final_data = []
    for row in rows:
        cells = row.find_all('td')
        if not cells: continue
        link_tag = cells[0].find('a')
        if not link_tag: continue
        
        filename = link_tag.text
        path = "https://download.osmand.net" + link_tag.get('href')
        cleaned_en = clean_name(filename)
        
        # לוקח תרגום קיים אם יש, אם לא - משאיר ריק כרגע
        he_name = existing_map.get(cleaned_en, "")
        
        final_data.append({
            "he_name": he_name,
            "en_name": cleaned_en,
            "path": path
        })

    # שמירה ראשונית של כל הקבצים שנמצאו
    save_json(final_data)
    print(f"נמצאו {len(final_data)} קבצים. השלד נשמר ל-JSON. מתחיל תרגום...", flush=True)

    # 4. לולאת תרגום עם שמירה אחרי כל פריט
    translator = Translator()
    
    for i, item in enumerate(final_data):
        # אם כבר יש תרגום, מדלגים
        if item["he_name"] != "":
            continue
            
        cleaned_en = item["en_name"]
        lower_name = cleaned_en.lower()
        
        # טיפול ידני במקרים מיוחדים
        if "israel" in lower_name:
            translated_he = "ישראל הקטנה"
        elif "palestine" in lower_name:
            translated_he = "שטחי יש\"ע"
        else:
            try:
                print(f"[{i+1}/{len(final_data)}] מתרגם: {cleaned_en}", flush=True)
                translated_he = translator.translate(cleaned_en, dest='he', src='en').text
                # השהייה קלה למניעת חסימה
                time.sleep(1.2)
            except Exception as e:
                print(f"שגיאה בתרגום {cleaned_en}: {e}", flush=True)
                translated_he = cleaned_en # גיבוי לאנגלית במקרה של שגיאה

        # עדכון הפריט ברשימה ושמירה מיידית לקובץ
        item["he_name"] = translated_he
        save_json(final_data)

    print("הסתיים בהצלחה! כל הנתונים מעודכנים ב-maps_data.json", flush=True)

if __name__ == "__main__":
    main()

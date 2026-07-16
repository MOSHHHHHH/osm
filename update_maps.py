import requests
from bs4 import BeautifulSoup
import json
import os
from googletrans import Translator
import time

def clean_name(filename):
    name = filename.replace('.obf.zip', '').replace('.voice.zip', '').replace('.extra.zip', '')
    name = name.replace('_', ' ')
    return name

def main():
    url = "https://download.osmand.net/list.php"
    # טעינת נתונים קיימים כדי לחסוך בתרגומים
    existing_data = {}
    if os.path.exists('maps_data.json'):
        try:
            with open('maps_data.json', 'r', encoding='utf-8') as f:
                old_list = json.load(f)
                # יצירת מילון לחיפוש מהיר לפי שם מקורי
                existing_data = {item['en_name']: item['he_name'] for item in old_list}
        except:
            pass

    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    translator = Translator()
    
    new_data_list = []
    rows = soup.find_all('tr')[1:]
    
    print(f"Total files found: {len(rows)}")

    for row in rows:
        cells = row.find_all('td')
        if not cells: continue
        link_tag = cells[0].find('a')
        if not link_tag: continue
        
        filename = link_tag.text
        path = "https://download.osmand.net" + link_tag.get('href')
        cleaned_en = clean_name(filename)

        # בדיקה אם התרגום כבר קיים אצלנו
        if cleaned_en in existing_data:
            translated_he = existing_data[cleaned_en]
        else:
            # אם לא קיים, מתרגמים (רק פריטים חדשים!)
            try:
                # החרגות ידניות
                if "israel" in cleaned_en.lower():
                    translated_he = "ישראל הקטנה"
                elif "palestine" in cleaned_en.lower():
                    translated_he = "שטחי יש\"ע"
                else:
                    print(f"Translating new item: {cleaned_en}")
                    translated_he = translator.translate(cleaned_en, dest='he', src='en').text
                    time.sleep(1) # השהייה ארוכה יותר לביטחון, כי זה קורה רק לעיתים רחוקות
            except:
                translated_he = cleaned_en # גיבוי לאנגלית

        new_data_list.append({
            "he_name": translated_he,
            "en_name": cleaned_en,
            "path": path
        })

    with open('maps_data.json', 'w', encoding='utf-8') as f:
        json.dump(new_data_list, f, ensure_ascii=False, indent=4)
    
    print("Update complete!")

if __name__ == "__main__":
    main()

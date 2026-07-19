print("הפעולה התחילה", flush=True)

import requests
from bs4 import BeautifulSoup
import json
import os
import re

# ==== הגדרות Gemini ====
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")  # שם המשתנה של מפתח ה-API
GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

SYSTEM_PROMPT = (
    "אתה מתרגם שמות של קבצי מפות גיאוגרפיות (מדינות, מחוזות, אזורים) מאנגלית לעברית. "
    "תרגם את השם הבא לשם העברי המקובל והרשמי ביותר של האזור/המדינה/המחוז, "
    "כפי שהוא מופיע במקורות רשמיים או במפות בעברית. "
    "אם מדובר בשם מחוז/מדינה בתוך מדינה גדולה יותר (כמו מדינות בארה\"ב, מחוזות בקנדה וכו'), "
    "תרגם את שם האזור עצמו בלבד, ללא הוספת הסברים. "
    "החזר אך ורק את התרגום לעברית, ללא מרכאות, ללא הסברים, ללא טקסט נוסף, ללא תגובה באנגלית."
)

def clean_name(filename):
    # הסרת סיומות
    name = filename.replace('.obf.zip', '').replace('.voice.zip', '').replace('.extra.zip', '')
    # החלפת קו תחתון ברווח
    name = name.replace('_', ' ')
    # הסרת מספרים (2, 0 וכו')
    name = re.sub(r'\d+', '', name)
    # ניקוי רווחים כפולים
    name = " ".join(name.split())
    return name

def save_json(data):
    with open('maps_data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def translate_with_gemini(text_to_translate):
    """מתרגם מחרוזת אחת לעברית באמצעות Gemini API. זורק חריגה במקרה של כשל."""
    payload = {
        "system_instruction": {
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": text_to_translate}]}
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 50
        }
    }
    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}

    resp = requests.post(GEMINI_URL, headers=headers, params=params, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    candidates = data.get("candidates")
    if not candidates:
        raise ValueError(f"אין תשובה מ-Gemini: {data}")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts or "text" not in parts[0]:
        raise ValueError(f"מבנה תשובה לא צפוי מ-Gemini: {data}")

    translated = parts[0]["text"].strip()
    if not translated:
        raise ValueError("Gemini החזיר תשובה ריקה")

    return translated

def main():
    if not GEMINI_API_KEY:
        print("שגיאה: לא נמצא מפתח API. יש להגדיר את משתנה הסביבה GEMINI_API_KEY.", flush=True)
        return

    url = "https://download.osmand.net/list.php"

    existing_map = {}
    if os.path.exists('maps_data.json'):
        try:
            with open('maps_data.json', 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                existing_map = {item['en_name']: item['he_name'] for item in old_data if item.get('he_name')}
        except:
            print("יוצר קובץ JSON חדש...", flush=True)

    print("מושך נתונים מאתר OsmAnd...", flush=True)
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

    print(f"נסרקו {len(final_data)} קבצים. מתחיל תרגום (מוגבל ל-500 פריטים חדשים)...", flush=True)

    translation_count = 0
    limit = 500  # מגבלה לריצה אחת

    for i, item in enumerate(final_data):
        if item["he_name"] != "":
            continue

        if translation_count >= limit:
            print(f"הגענו למגבלת {limit} תרגומים לריצה זו. עוצרים ושומרים.", flush=True)
            break

        # הכנה לתרגום: החלפת מקפים ברווחים לשיפור הדיוק
        text_to_translate = item["en_name"].replace('-', ' ')

        lower_name = item["en_name"].lower()
        if "israel" in lower_name:
            translated_he = "ישראל הקטנה"
        elif "palestine" in lower_name:
            translated_he = "שטחי יש\"ע"
        else:
            try:
                print(f"[{i+1}/{len(final_data)}] מתרגם: {text_to_translate}...", end=" ", flush=True)
                translated_he = translate_with_gemini(text_to_translate)
                print(f"הצליח: {translated_he}", flush=True)
                translation_count += 1
            except Exception as e:
                print(f"\nחסימה או שגיאה ב-Gemini. שומר ועוצר. שגיאה: {e}", flush=True)
                break

        item["he_name"] = translated_he
        save_json(final_data)

    save_json(final_data)
    print(f"הריצה הסתיימה. תורגמו {translation_count} פריטים חדשים.", flush=True)

if __name__ == "__main__":
    main()

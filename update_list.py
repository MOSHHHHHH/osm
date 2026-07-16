import os
import re
import json
from bs4 import BeautifulSoup
from googletrans import Translator

def clean_filename(filename):
    # הסרת סיומת הקובץ (למשל .zip, .obf וכדומה)
    name_without_ext = os.path.splitext(filename)[0]
    # הסרת קו תחתי (_) בלבד, תוך שמירה על מקפים (-)
    cleaned_name = name_without_ext.replace('_', ' ')
    return cleaned_name

def process_and_translate():
    # בדיקה שהקובץ שהורד אכן קיים
    if not os.path.exists('list.html'):
        print("Error: list.html not found!")
        return

    # קריאת קובץ ה-HTML
    with open('list.html', 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    # שליפת כל הקישורים (נתיבים) מהטבלה/דף
    links = soup.find_all('a')
    
    data_to_translate = []
    seen_paths = set()

    for link in links:
        path = link.get('href')
        if not path:
            continue
            
        # סינון קישורים שאינם קבצים להורדה (למשל תיקיות אב או קישורים חיצוניים)
        if path.startswith('?') or path.startswith('/') or '://' in path:
            continue

        filename = os.path.basename(path)
        if not filename or path in seen_paths:
            continue

        seen_paths.add(path)
        cleaned_name = clean_filename(filename)
        
        data_to_translate.append({
            "path": path,
            "original_name": cleaned_name
        })

    if not data_to_translate:
        print("No files found to process.")
        return

    print(f"Found {len(data_to_translate)} files. Starting translation...")

    # אתחול המתרגם
    translator = Translator()
    translated_results = []

    # תרגום הנתונים בקבוצות (Batch) כדי למנוע עומס וחסימות מול גוגל
    batch_size = 20
    for i in range(0, len(data_to_translate), batch_size):
        batch = data_to_translate[i:i+batch_size]
        texts_to_translate = [item["original_name"] for item in batch]
        
        try:
            # תרגום לעברית
            translations = translator.translate(texts_to_translate, dest='he')
            
            for item, translation in zip(batch, translations):
                translated_results.append({
                    "path": item["path"],
                    "name_he": translation.text
                })
        except Exception as e:
            print(f"Translation error at index {i}: {e}")
            # במקרה של שגיאת תרגום, נשמור את השם המקורי המנוקה
            for item in batch:
                translated_results.append({
                    "path": item["path"],
                    "name_he": item["original_name"]
                })

    # ייצוא ל-JSON
    with open('list.json', 'w', encoding='utf-8') as json_file:
        json.dump(translated_results, json_file, ensure_ascii=False, indent=4)

    print("Success: list.json has been created!")

if __name__ == "__main__":
    process_and_translate()

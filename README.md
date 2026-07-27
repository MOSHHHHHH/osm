# מפות אופליין — OsmAnd &amp; מובידוס

אתר GitHub Pages להורדה חופשית וללא הגבלה של מפות אופליין עבור OsmAnd ונתוני מובידוס.

## מבנה הפרויקט

```
index.html                     דף הבית
privacy-policy.html            מדיניות פרטיות
js/app.js                      לוגיקת הצד-לקוח (חיפוש, הורדות, מודאל סטטוס)
data/osmand-data.json          מסד כל קבצי ה-obf (נכתב אוטומטית)
data/mapsTags.json             תגיות עברית/אנגלית לכל קובץ (נכתב אוטומטית)
data/moovitdos-link.json       קישור לקובץ הנתונים העדכני של מובידוס (נכתב אוטומטית)
data/update-status.json        מצב העדכון האחרון של שני המקורות (נכתב אוטומטית)
files/                         קבצי ה-obf עצמם (מנוהלים אוטומטית)
update-scripts/data-update.py  מריץ יומי (00:00) — מעדכן OsmAnd + מובידוס
update-scripts/tag-generator.py מריץ יומי (06:00) — יוצר תגיות באמצעות Gemini
.github/workflows/              הרצה אוטומטית יומית + הרצה ידנית (workflow_dispatch)
```

## הפעלה ראשונית

1. **דחפו (push) את התוכן הזה למאגר GitHub חדש**, ובGitHub Pages settings הגדירו
   פריסה מ-branch `main`, תיקיית root.
2. **הוסיפו secret בשם `GEMINI_API_KEY`** תחת Settings → Secrets and variables →
   Actions, עם מפתח ה-API של Gemini שלכם.
3. ודאו ש-Settings → Actions → General → Workflow permissions מוגדר ל-
   **"Read and write permissions"**, כדי שה-workflows יוכלו לדחוף (push) עדכונים בחזרה למאגר.
4. אפשר להריץ את שני ה-workflows באופן ידני (tab **Actions** → בחרו workflow →
   **Run workflow**) כדי לבדוק שהכול עובד לפני שממתינים ליום הראשון של ריצה אוטומטית.

## הערות טכניות

- ה-cron של GitHub Actions תמיד לפי UTC ואינו זז עם שעון קיץ/חורף ישראלי — ראו
  הערה בכל קובץ workflow לגבי הפער המשוער.
- `data-update.py` מוריד ומחלץ רק קבצי `*.obf.zip` מרשימת OsmAnd; כל סוג קובץ אחר
  ברשימה מתעלם ממנו לחלוטין.
- מובידוס: מכיוון שדף ה-GitHub Pages של מובידוס טוען את קישור ההורדה באמצעות JS,
  והמאגר המקורי כנראה פרטי, הסקריפט מחלץ מספר גרסה מתוך הדף עצמו ובונה את כתובת
  ה-URL הידועה (`.../releases/download/v{X}/moovidos_data_v{X}.zip`). קובץ הנתונים
  של מובידוס עצמו **אינו** מועתק למאגר הזה — רק הכתובת נשמרת, וההורדה מתבצעת ישירות
  מול GitHub.
- מפתח ה-Gemini API אף פעם לא נחשף בצד הלקוח — הוא משמש רק בתוך ה-workflow של
  `tag-generator.py`, בצד השרת.

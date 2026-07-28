# מפות אופליין — OsmAnd &amp; מובידוס

אתר GitHub Pages להורדה חופשית וללא הגבלה של מפות אופליין עבור OsmAnd ונתוני מובידוס.
Built with love for the students of the Hebron Yeshiva and other users.
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

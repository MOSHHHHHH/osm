(function() {
    // 1. הזרקת עיצוב מותאם אישית למודאל התחזוקה
    const style = document.createElement('style');
    style.innerHTML = `
        .maintenance-overlay {
            position: fixed;
            inset: 0;
            background: rgba(34, 29, 26, 0.7);
            backdrop-filter: blur(4px);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            z-index: 9999;
            animation: fadeIn 0.3s ease-out;
        }

        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

        .maintenance-card {
            background: var(--cream);
            border-radius: 24px;
            max-width: 550px;
            width: 100%;
            padding: 40px;
            box-shadow: 0 40px 80px -20px rgba(0,0,0,0.5);
            border: 2px solid var(--orange);
            text-align: center;
            position: relative;
            overflow: hidden;
            animation: pop 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }

        .maintenance-card h2 {
            font-family: 'Rubik', sans-serif;
            font-size: 2rem;
            color: var(--orange-deep);
            margin: 20px 0 10px;
            font-weight: 900;
        }

        .maintenance-card p {
            font-family: 'Heebo', sans-serif;
            font-size: 1.15rem;
            color: var(--ink);
            line-height: 1.5;
            margin-bottom: 25px;
        }

        .maintenance-icon {
            font-size: 4rem;
            display: block;
            margin-bottom: 10px;
        }

        .maintenance-trail {
            width: 100%;
            max-width: 300px;
            margin: 0 auto 25px;
            display: block;
        }

        .maintenance-btn {
            background: linear-gradient(160deg, var(--orange), var(--orange-deep));
            color: white;
            border: none;
            padding: 14px 40px;
            border-radius: 14px;
            font-family: 'Rubik', sans-serif;
            font-weight: 700;
            font-size: 1.1rem;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 10px 20px -5px rgba(232, 98, 12, 0.4);
        }

        .maintenance-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 15px 25px -5px rgba(232, 98, 12, 0.5);
        }

        .maintenance-badge {
            display: inline-block;
            background: rgba(232, 98, 12, 0.1);
            color: var(--orange-deep);
            padding: 6px 15px;
            border-radius: 999px;
            font-size: 0.85rem;
            font-weight: 700;
            margin-bottom: 10px;
        }
    `;
    document.head.appendChild(style);

    // 2. יצירת ה-HTML של המודאל
    const modalHTML = `
        <div class="maintenance-overlay" id="maintenanceModal">
            <div class="maintenance-card">
                <div class="maintenance-badge">עדכון מערכת</div>
                <span class="maintenance-icon">🛠️</span>
                <h2>האתר בתחזוקה</h2>
                <svg class="maintenance-trail" viewBox="0 0 320 40" preserveAspectRatio="none">
                    <path d="M10,20 C80,40 150,0 220,20 C270,35 310,10 310,10" fill="none" stroke="#E8620C" stroke-width="3" stroke-dasharray="6 8" />
                </svg>
                <p>יתכנו תקלות זמניות בגישה לקבצים.<br>אנחנו פועלים ברגעים אלו כדי לתקן את הבעיה ולהחזיר את השירות לפעילות מלאה.</p>
                <button class="maintenance-btn" onclick="document.getElementById('maintenanceModal').remove()">הבנתי, תודה</button>
            </div>
        </div>
    `;

    // 3. הזרקה לדף כשהוא נטען
    document.addEventListener('DOMContentLoaded', () => {
        document.body.insertAdjacentHTML('beforeend', modalHTML);
        
        // הפעלת Twemoji אם קיים בדף
        if (typeof twemoji !== 'undefined') {
            twemoji.parse(document.getElementById('maintenanceModal'));
        }
    });
})();
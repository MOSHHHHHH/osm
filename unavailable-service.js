(function() {
    // 1. הזרקת עיצוב להודעה הקופצת
    const style = document.createElement('style');
    style.innerHTML = `
        .maintenance-toast {
            position: fixed;
            top: -150px; /* מתחיל מחוץ למסך */
            left: 50%;
            transform: translateX(-50%);
            width: 90%;
            max-width: 450px;
            background: var(--cream);
            border: 2px solid var(--line);
            border-top: 4px solid var(--orange);
            border-radius: 18px;
            padding: 16px 20px;
            box-shadow: var(--shadow);
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 8px;
            transition: top 0.6s cubic-bezier(0.68, -0.55, 0.265, 1.55);
            font-family: 'Heebo', sans-serif;
            overflow: hidden;
        }

        .maintenance-toast.show {
            top: 25px;
        }

        .toast-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .toast-title {
            display: flex;
            align-items: center;
            gap: 8px;
            font-family: 'Rubik', sans-serif;
            font-weight: 700;
            color: var(--orange-deep);
            font-size: 1.05rem;
        }

        .toast-close {
            background: none;
            border: none;
            font-size: 1.2rem;
            cursor: pointer;
            color: var(--muted);
            padding: 0 5px;
            line-height: 1;
        }

        .toast-body {
            font-size: 0.92rem;
            color: var(--ink);
            line-height: 1.4;
            margin-bottom: 5px;
        }

        /* ה-SVG המוקטן של האתר */
        .toast-trail {
            width: 100px;
            height: 20px;
            margin-top: -5px;
        }

        /* פס התקדמות */
        .toast-progress-container {
            position: absolute;
            bottom: 0;
            left: 0;
            width: 100%;
            height: 4px;
            background: var(--line);
            opacity: 0.5;
        }

        .toast-progress-bar {
            height: 100%;
            background: var(--orange);
            width: 100%;
            transition: width 7s linear; /* תואם לזמן התצוגה */
        }
    `;
    document.head.appendChild(style);

    // 2. פונקציית יצירת והצגת ההודעה
    function showMaintenanceToast() {
        const toastHTML = `
            <div class="maintenance-toast" id="maintenanceToast">
                <div class="toast-header">
                    <div class="toast-title">
                        <span>🛠️</span>
                        <span>האתר בתחזוקה</span>
                    </div>
                    <button class="toast-close" id="closeToast">✕</button>
                </div>
                <div class="toast-body">
                    יתכנו תקלות זמניות, אנו פועלים לתקן את הבעיה.
                    <svg class="toast-trail" viewBox="0 0 100 20" preserveAspectRatio="none">
                        <path d="M0,10 C30,20 60,0 100,10" fill="none" stroke="#E8620C" stroke-width="3" stroke-dasharray="4 4" />
                    </svg>
                </div>
                <div class="toast-progress-container">
                    <div class="toast-progress-bar" id="toastProgress"></div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', toastHTML);
        const toast = document.getElementById('maintenanceToast');
        const progressBar = document.getElementById('toastProgress');
        const closeBtn = document.getElementById('closeToast');

        // הפעלת Twemoji אם קיים
        if (typeof twemoji !== 'undefined') twemoji.parse(toast);

        // הצגת ההודעה (אנימציה)
        setTimeout(() => {
            toast.classList.add('show');
            progressBar.style.width = '0%'; // מתחיל את האנימציה של הפס
        }, 100);

        // פונקציית סגירה
        const closeToast = () => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 600);
        };

        closeBtn.onclick = closeToast;

        // סגירה אוטומטית אחרי 7 שניות
        setTimeout(closeToast, 7000);
    }

    // 3. תזמון: מופיע 7 שניות לאחר טעינת הדף
    window.addEventListener('load', () => {
        setTimeout(showMaintenanceToast, 7000);
    });
})();

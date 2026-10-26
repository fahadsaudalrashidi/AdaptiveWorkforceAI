# THRIVE - منصة الذكاء المؤسسي والذكاء التنفيذي (AWI)

**Adaptive Workforce Intelligence | Executive Analytics Platform**

THRIVE brings workforce, financial, and operational analysis into one bilingual
workspace. It helps teams explore company data, track important indicators, and
turn questions into clear, evidence-based insights. Local analysis is available
without a paid AI service.

[العربية](#العربية) · [English](#english)

---

## العربية

### نبذة عن المنصة

THRIVE منصة مؤسسية ثنائية اللغة (العربية والإنجليزية) لتحليل بيانات الموارد
البشرية والمالية والعمليات واللوجستيات. تجمع لوحات التحليل والاستعلامات
التنفيذية في مساحة عمل واحدة، مع دعم عرض العربية من اليمين إلى اليسار.
يمكن تحليل الملفات محلياً دون الاعتماد على خدمة ذكاء اصطناعي مدفوعة.

### الوحدات والميزات

#### تحليلات الموارد البشرية وإدارة القوى العاملة

- متابعة انتهاء العقود والإقامات والتأشيرات ومواعيد التجديد.
- مؤشرات جاهزية التعاقب الوظيفي واستمرارية المناصب.
- مؤشرات الامتثال ومتابعة الاستثناءات.
- تحليلات الرواتب وتكاليف العمل الإضافي.
- رؤى مسارات التوظيف ومؤشرات المغادرة ومقابلات الخروج.

#### الذكاء المالي والمحاسبي

- تحليلات الإيرادات والمصروفات والأداء المالي.
- تقارير الأرباح والخسائر (P&L) والتدفق النقدي.
- تحليل الأستاذ العام ومراجعة القيود المالية.
- تحليل أعمار الذمم المدينة (AR Aging).

#### ذكاء العمليات واللوجستيات

- استعلامات تجارية وتنفيذية باللغة الطبيعية على البيانات المتاحة.
- متابعة المخزون وتصنيف ABC.
- مؤشرات أداء شركات النقل والأسطول والعمليات اللوجستية.

#### تحليل الملفات

يدعم مسار التحليل المحلي ملفات CSV وExcel (`.xls` و`.xlsx`) وPDF وJSON.
تعتمد التحليلات المحلية على معالجة قابلة للتدقيق؛ وقد تتطلب المستندات الممسوحة
ضوئياً تثبيت Tesseract وبيانات اللغتين العربية والإنجليزية. أي تكامل مع خدمة
ذكاء اصطناعي خارجية اختياري، وليس شرطاً للتحليلات المحلية.

### التقنيات

| الطبقة | التقنيات |
| --- | --- |
| الواجهة الأمامية | React 18، TypeScript، Vite، Tailwind CSS |
| الواجهة الخلفية | Python 3.12، FastAPI، Uvicorn |
| معالجة البيانات والملفات | pandas، NumPy، openpyxl، xlrd، pdfplumber، PDFium |
| قاعدة البيانات | SQLite للتطوير المحلي؛ PostgreSQL للإنتاج |
| المصادقة | حسابات محلية باسم مستخدم وكلمة مرور، رموز JWT، تجزئة كلمات المرور، وصلاحيات حسب الدور |
| التعرف الضوئي على الحروف | Tesseract للغة العربية والإنجليزية عند تفعيل OCR للملفات الممسوحة |

### التشغيل محلياً

**المتطلبات:** Python 3.12 أو أحدث، وNode.js 20 أو أحدث. عند الحاجة إلى OCR
لملفات PDF الممسوحة، ثبّت Tesseract وبيانات اللغتين العربية والإنجليزية.

من مجلد المشروع:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements-replit.txt
npm --prefix executive-ui ci
```

شغّل الواجهة الخلفية في نافذة طرفية:

```bash
python -m uvicorn backend.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

وشغّل الواجهة الأمامية في نافذة أخرى:

```bash
npm --prefix executive-ui run dev
```

افتح `http://localhost:5000`. تقوم Vite بتمرير طلبات `/api` إلى الواجهة الخلفية.
تتوفر حالة الخدمة في `/api/v1/status` ووثائق API في `/api/v1/docs`.
تستخدم بيئة التطوير SQLite للمصادقة المحلية افتراضياً.

### الإعداد والأمان

- أنشئ الحساب الإداري الأول عبر إعداد `AWI_ADMIN_BOOTSTRAP_PASSWORD` في مدير
  أسرار آمن قبل تشغيل التطبيق. تفرض المنصة تغيير كلمة المرور عند أول تسجيل دخول.
- في الإنتاج، اضبط `SESSION_SECRET` بطول لا يقل عن 32 حرفاً، واستخدم PostgreSQL
  عبر `DATABASE_URL` الذي يوفره مزود قاعدة البيانات.
- تتطلب بيئة الإنتاج المصادقة عبر PostgreSQL؛ ولا تتحول تلقائياً إلى SQLite
  عند تعذر الاتصال بقاعدة البيانات.
- لا تضع كلمات المرور أو مفاتيح API أو رموز الوصول في هذا الملف أو في Git.
  أدرها من خلال Replit Secrets أو مدير أسرار مناسب لبيئتك.
- يُبنى إصدار الإنتاج بواسطة `bash build-production.sh` ويُشغّل بواسطة
  `bash start-production.sh`. في Replit، استخدم سير العمل المُعدّ وزر **Publish**.

### الاختبارات والبناء

```bash
python -m pytest tests/ -q
python -m unittest discover -s backend/tests
npm --prefix executive-ui run build
```

---

## English

### Executive summary

THRIVE is a bilingual (Arabic and English) enterprise analytics platform for
workforce, finance, accounting, operations, and logistics. It brings dashboards
and executive data queries into one workspace, helping teams monitor indicators
and explore evidence from company files. Local analysis works without a paid
AI service.

### Core modules and features

#### HR & Workforce Analytics

- Track contract, residency permit (Iqama), and visa expirations and renewal dates.
- Review succession readiness and continuity indicators for key positions.
- Monitor compliance indicators and exceptions.
- Analyze payroll and overtime costs.
- Explore recruitment pipelines, departures, and exit-interview insights.

#### Finance & Accounting Intelligence

- Analyze revenue, expenses, and financial performance.
- Review profit and loss (P&L) and cash flow.
- Explore general-ledger activity and financial entries.
- Analyze accounts-receivable aging (AR Aging).

#### Operations & Logistics Intelligence

- Ask commercial and executive questions about available company data.
- Monitor inventory and ABC classification.
- Review carrier, fleet, and logistics performance indicators.

#### File analysis

The local analysis workflow supports CSV, Excel (`.xls` and `.xlsx`), PDF, and
JSON files. Local analytics use auditable data processing and do not require a
paid AI provider. Scanned PDFs may require Tesseract plus Arabic and English
language data. External AI-provider integration is optional.

### Technology stack

| Layer | Technologies |
| --- | --- |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS |
| Backend | Python 3.12, FastAPI, Uvicorn |
| Data and document processing | pandas, NumPy, openpyxl, xlrd, pdfplumber, PDFium |
| Database | SQLite for local development; PostgreSQL for production |
| Authentication | Local username/password accounts, JWT tokens, password hashing, and role-based access |
| OCR | Tesseract for Arabic and English scanned-document recognition when enabled |

### Local setup

**Prerequisites:** Python 3.12 or later and Node.js 20 or later. For OCR on
scanned PDFs, install Tesseract and its Arabic and English language data.

From the project root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements-replit.txt
npm --prefix executive-ui ci
```

Start the backend in one terminal:

```bash
python -m uvicorn backend.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

Start the frontend in another:

```bash
npm --prefix executive-ui run dev
```

Open `http://localhost:5000`. Vite proxies `/api` requests to the backend.
Service status is available at `/api/v1/status`; API documentation is at
`/api/v1/docs`. Local development uses SQLite for authentication by default.

### Configuration and security

- Create the initial administrator by setting `AWI_ADMIN_BOOTSTRAP_PASSWORD`
  through a secure secrets manager before starting the application. The
  administrator must change the password at first sign-in.
- Production requires a stable `SESSION_SECRET` of at least 32 characters and
  PostgreSQL through the provider-managed `DATABASE_URL`.
- Production authentication requires PostgreSQL. The app does not silently
  fall back to SQLite if the database is unavailable.
- Do not put passwords, API keys, or access tokens in this file or in Git.
  Manage them with Replit Secrets or an appropriate secrets manager.
- Build production with `bash build-production.sh` and run it with
  `bash start-production.sh`. On Replit, use the configured workflows and the
  **Publish** action.

### Tests and production build

```bash
python -m pytest tests/ -q
python -m unittest discover -s backend/tests
npm --prefix executive-ui run build
```

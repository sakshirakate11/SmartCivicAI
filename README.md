# SmartCivicAI

React/Vite frontend and a Flask + SQLite API prototype. Complaint records and uploaded images are stored by the local backend, not in a remote service.
The backend writes to `backend/data/smartcivic.db` and stores validated images under `backend/uploads/` by default. These paths are relative to `backend/`, not the terminal's current directory. Do not remove either folder when restarting the app.

## Start the backend (PowerShell)

Open a VS Code terminal at the project root:

```powershell
cd "C:\Users\hp\OneDrive\Desktop\SmartCivicAI\backend"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy the generated value into `backend/.env` as `SECRET_KEY=...`. Keep `.env` private and out of source control. Then initialize SQLite and provision municipal/admin accounts (the commands prompt for passwords):

```powershell
python manage.py init-db
python manage.py create-user --role municipal --email officer@example.test --name "Municipal Officer"
python manage.py create-user --role department --department "Roads & Transport" --email roads@example.test --name "Roads Officer"
python manage.py create-user --role admin --email admin@example.test --name "City Administrator"
python app.py
```

The API starts at `http://127.0.0.1:5000`. Department accounts sign in at **Department login**; their queue and complaint actions are restricted to the department selected at account creation. Only the currently assigned department officer can accept a complaint, start work, add progress notes, or complete it. Municipal officers have read-only access to the citywide complaint queue, status history, and analytics. Administrators may manage department assignment and priority, but cannot change operational complaint status.

All department accounts use the same department dashboard, filtered to their assigned team: Water Works, Sanitation, Roads & Transport, Electrical, Municipal ward office, Parks & Gardens, or Public Health. Complaint routing is based only on the category selected in the citizen form:

| Category | Assigned department |
| --- | --- |
| Roads & pathways | Roads & Transport |
| Waste management | Sanitation |
| Water supply | Water Works |
| Drainage & flooding | Water Works |
| Street lighting | Electrical |
| Public health | Public Health |
| Parks & gardens | Parks & Gardens |
| Other | Municipal ward office |

Descriptions are required for text-only reports and may be omitted when a photo is attached. If a future supported category has no mapping, it is stored for municipal/admin review and is not exposed to a department queue until an authorized user assigns it.

The backend runs an overdue reminder job after the first API request. It marks open complaints overdue after `OVERDUE_AFTER_HOURS` (72 by default) and creates persistent notifications, repeating no more than once every 24 hours per complaint. `OVERDUE_REMINDER_INTERVAL_SECONDS` controls the background check interval (3600 seconds by default). These settings can be placed in `backend/.env`.

Account roles and department assignments are held in SQLite and checked against signed expiring bearer tokens. This prototype does not provide password reset, email verification, rate limiting, or production deployment hardening.

## Start the frontend

Open a second VS Code terminal at the project root:

```powershell
cd "C:\Users\hp\OneDrive\Desktop\SmartCivicAI"
npm install
Copy-Item .env.example .env
npm run dev
```

Vite prints the frontend address, usually `http://localhost:5173`. The backend `.env` allows both `localhost` and `127.0.0.1:5173` by default. If the Vite origin changes, update `FRONTEND_ORIGINS` in `backend/.env`.

## Backup and migrate old browser complaints

The previous frontend used `localStorage["smartcivic.complaints.v1"]`, a JSON array of complaints. It includes display names and display dates rather than authenticated citizen IDs or authoritative timestamps; optional photos are compressed data URLs.

The new app does not use that key as complaint storage and does not clear or rewrite it. Dashboard records are fetched from SQLite after sign-in. After signing in as a citizen, open **My complaints → Legacy browser backup** to explicitly import older browser-local data:

1. Download the JSON backup before migration. Keep it in a private location; it may contain complaint text and images.
2. Review the records. Importing assigns every selected legacy entry to the currently authenticated citizen and creates new server complaint IDs. Legacy names and dates cannot be verified or preserved as account identity/audit metadata.
3. Explicitly check the confirmation and import the browser data or the downloaded JSON. Imports are transactional and the server rejects a repeat import of the same legacy IDs for that citizen.

The original localStorage key is intentionally retained as a backup until you choose to import it. New complaints and updates are written to SQLite; local React state only reflects the latest API response. After a browser restart, sign in again to reload records from the backend. The API and SQLite database are local development resources and do not synchronize across machines unless separately deployed and secured.

The API applies additive SQLite migrations when it starts. Existing users and complaints keep their data; records in older databases receive the default `Medium` priority and an initial department-assignment history entry. Department workflow status, progress notes, assignment history, review flags, and notifications are stored in SQLite. Do not delete or recreate `backend/data/smartcivic.db` to apply a migration.

## Verified routing, ML recommendations, ETA, escalation, and delivery

Complaint assignment uses the citizen-selected category and the verified SQLite `category_department_mappings` table; an ML prediction can never select or override the department. The built-in mapping is listed above and is seeded additively, without replacing existing verified corrections. Unmapped categories are held for municipal review. Authorized global municipal officers and administrators can review and correct mappings in the dashboard; each change records the old/new department, reason, user, and time, and routes pending unmapped reports for that category. Department officers cannot edit mappings.

The local TF-IDF classifier is advisory only. Ordinary historical complaints are not treated as verified training labels. Authorized municipal/admin users can add verified examples (either an existing complaint ID or a reviewed description), correct/remove examples, and inspect the audit trail through the dashboard. Training and evaluation use only this verified dataset. Evaluation uses stratified k-fold cross-validation only when at least five examples exist for every represented category and there are at least two categories; otherwise it explicitly reports insufficient data and no accuracy. A retraining run stores its metrics and model artifact in SQLite; an artifact becomes available for recommendations only after sufficient evaluation. Metrics are dataset-specific, are not a production reliability claim, and never affect routing. Department officers cannot view citywide metrics or manage the dataset/model.

New complaint records expose the citizen-selected category, predicted category/confidence, and actual assigned department separately. When no evaluated model exists, confidence is low, or a category has no mapping, the complaint is flagged for municipal review as appropriate. Image-only submissions are routed from their selected category without classification.

Priority, urgency, dissatisfaction, and sentiment indicators are transparent keyword rules, not trained models or medical/emotional assessments. Priority suggestions may be `Critical`; the existing operational priority field remains `Low`, `Medium`, or `High`, so a critical suggestion is stored as `High` while retaining `Critical` as the prediction. Similar-report suggestions use TF-IDF text similarity. GPS hotspots use submitted coordinates only and approximate clusters by rounding to 0.01 degree; no location is inferred for complaints without GPS.

An ETA uses the historical median for the same category and department when at least five completed reports are available. Otherwise `ETA_FALLBACK_HOURS` (72 by default), predicted priority, and current department workload determine a clearly labeled rule-based estimate. ETAs are not guarantees; the assigned department officer can update one from the department dashboard. `UNACCEPTED_AFTER_HOURS` (24 by default) controls escalation visibility for complaints still pending acceptance. Existing `OVERDUE_AFTER_HOURS` controls overdue reminders.

In-app notifications are stored in SQLite and available from the authenticated notifications panel. Complaint assignment, status changes, ETA updates, progress notes, and escalations create in-app notices. Email notifications use the Brevo transactional email API and require `BREVO_API_KEY` and `BREVO_SENDER_EMAIL` in `backend/.env`; `BREVO_SENDER_NAME` is optional and defaults to `SmartCivicAI`. The sender address must be verified in Brevo. The API key remains on the backend; email delivery results, provider response, and timestamps are stored in SQLite. Missing credentials and provider errors are recorded rather than reported as success. Tests mock Brevo responses and never send real email. Run `python -m unittest discover -s tests -v` from `backend/` and `npm run build` from the project root to verify.

Citizens can rate a completed complaint once. Municipal users can view workload, escalation, and coordinate-cluster analytics but remain read-only for operational complaint status; only the assigned department officer can accept, start work, update progress/ETA, or complete it.

## Verify

```powershell
cd "C:\Users\hp\OneDrive\Desktop\SmartCivicAI\backend"
python -m unittest discover -s tests -v
cd "C:\Users\hp\OneDrive\Desktop\SmartCivicAI"
npm run build
```

## Deploy the existing project on Render

The root `render.yaml` describes two services for this project: the existing Flask API in `backend/` and the existing Vite frontend. No deployment is started by this file, and automatic deploys on future source changes are disabled. When you are ready, choose **New → Blueprint** in Render, connect this repository, and review the services and environment prompts before applying; applying the Blueprint starts the initial deployment. The API is configured with Gunicorn and a 1 GB persistent disk at `/var/data`; the web service uses a paid Starter instance because Render's free instance does not provide the persistent disk this SQLite-and-image setup needs. Increase the disk size if your records and images require more space.

### Before the first public deployment

1. Make a separate backup of `backend/data/smartcivic.db` and, if it exists, the entire `backend/uploads/` folder. These paths are ignored by Git and are not deployed with the source code.
2. Decide whether to carry the current local records to Render. A new Render disk starts empty. If you need those records, transfer the backed-up database and matching uploads to `/var/data` using a secure method before accepting real complaints. Do not overwrite a database that has already received production data with an older backup. Verify the migrated records and images before opening the site to the public.
3. In the Render API service environment, set `FRONTEND_ORIGINS` to the exact deployed frontend origin, such as `https://your-frontend.onrender.com` (no trailing slash). Include comma-separated origins only if you intentionally use more than one frontend domain.
4. To enable Brevo email, set `BREVO_API_KEY` and `BREVO_SENDER_EMAIL` in the API service. Verify the sender address in Brevo first. `BREVO_SENDER_NAME` is optional and defaults to `SmartCivicAI`. Keep the API key only in the backend environment; never put it in a `VITE_` variable.
5. In the frontend Static Site environment, set `VITE_API_URL` to the HTTPS API URL ending in `/api`, for example `https://your-api.onrender.com/api`. The production build rejects a missing, non-HTTPS, or incorrectly suffixed URL. Changing this variable requires a new frontend build.
6. Render generates `SECRET_KEY` from `render.yaml`; keep the generated value private and stable across deploys. `DATABASE_PATH` and `UPLOAD_FOLDER` are set by the Blueprint to `/var/data/smartcivic.db` and `/var/data/uploads`. Render supplies `PORT` automatically.
7. After deployment, open `https://your-api.onrender.com/api/health` and confirm it returns `{"status":"ok"}`. Then test sign-in, a complaint with an image, in-app notifications, and Brevo email (if configured). Restart the backend and verify the complaint and image remain available.

SQLite migrations in this application are additive and run on startup. They do not replace the database file, but the application cannot migrate local records that were not transferred to the persistent disk. Keep separate backups of the database and uploaded images.

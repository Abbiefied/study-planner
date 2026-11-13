# 📚 MDS Block Study Planner

A shared study tracker for two accountability partners (built for UBC MDS-style blocks: 5 weeks, 4 courses,
2 quizzes + 4 labs per course).

**Features**
- Daily plan: tasks by course / topic / lab with To do → In progress → Done
- Grades: weights per item, real grades, what-if grades for ungraded items, projected final,
  and the average you still need to hit your target
- Study log (minutes per session) and a dashboard with charts
- Weekly report: completed vs. not completed, hours, minutes by course, copy-ready text
- **Accountability:** each of you has your own tasks, grades, targets and log. You can open each other's
  planner read-only, compare this week side by side, and see a shared activity feed.
  Courses/weights and block dates are shared.

## Architecture

| Piece | What it is |
|---|---|
| `app.py` | Streamlit UI (login, 5 tabs) |
| `store.py` | Data layer. Postgres in production, SQLite locally. Writes are filtered by username |
| `calc.py` | Pure grade/week maths |
| `tests/` | Unit tests (`test_core.py`) and a whole-app smoke test (`smoke_app.py`) |

Streamlit Community Cloud has **no permanent disk**, so data lives in a free hosted Postgres
(Supabase or Neon). Without `database_url` the app uses a local SQLite file, which is fine on your laptop
but would be wiped on Streamlit Cloud.

## Deploy (about 15 minutes, all free tiers)

### 1. Create the database (Supabase)
1. Sign up at supabase.com, create a project, and save the database password.
2. Open the project's **Connect** / **Database settings** page and copy the **Postgres connection string**
   (URI form, `postgresql://...`) and put your password in it.
3. If the app later fails to connect from Streamlit Cloud, use the **connection-pooler** string
   from the same page instead of the direct one (the direct host can be IPv6-only).
4. Nothing else to do: the app creates its own tables on first start.

(Neon, Railway, Render or any Postgres works the same way; just paste its connection string.)

### 2. Put the code on GitHub
```bash
cd study-planner
git init && git add . && git commit -m "Study planner"
# create an empty repo on github.com, then:
git remote add origin https://github.com/<you>/study-planner.git
git branch -M main && git push -u origin main
```
`.gitignore` already keeps `secrets.toml` and `*.db` out of the repo.

### 3. Deploy on Streamlit Community Cloud
1. Go to share.streamlit.io, sign in with GitHub, **Create app**, pick the repo, branch `main`,
   main file `app.py`.
2. Open **Advanced settings → Secrets** and paste (edit the values):
   ```toml
   database_url = "postgresql://USER:PASSWORD@HOST:5432/postgres"
   timezone = "America/Vancouver"

   [users]
   Abbie = "pick-a-password"
   Buddy = "pick-another-password"
   ```
3. Deploy. Share the app URL and her password with your study buddy. The two names in `[users]`
   are the two accounts; change them to your real names.

### 4. First use
1. Log in, open **Dashboard → Block settings**, set the block number and the date week 1 starts.
2. **Grades → Add course** for each of your 4 courses. Replace the placeholder weights (20/20 for quizzes,
   15 each for labs) with the real syllabus weights; use **Add or remove items** for iClicker, oral check-in, etc.
   The tool warns when a course's weights don't total 100%.
3. Plan the day in **Daily plan**, log time in **Study log**, check **Weekly report** every Sunday.

## Troubleshooting the database connection
The app now shows the real error (without your password) instead of Streamlit's redacted one.
- *"Network is unreachable"* or an IPv6 address in the message: use Supabase's **Session pooler** string
  (`...pooler.supabase.com:5432`, user `postgres.<project-ref>`), not the direct `db.<ref>.supabase.co` one.
- *"password authentication failed"* / *"Tenant or user not found"*: wrong password, a leftover `[YOUR-PASSWORD]`
  placeholder (remove the square brackets), or a pooler user missing the `.<project-ref>` suffix.
- Special characters in the password are fine; the app percent-encodes them automatically.

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # edit; delete the database_url line to use SQLite
streamlit run app.py
```
Quick dev mode without a secrets file: `STUDY_DEV=1 streamlit run app.py` (users `me` and `buddy`, password `dev`).
Never set `STUDY_DEV` in production.

## Tests
```bash
python -m unittest discover -s tests -v   # grade maths + data layer (SQLite)
python tests/smoke_app.py                 # runs every tab with a fake Streamlit
```

## Notes and limits
- Passwords live in the app secrets and are compared in constant time. That is plenty for two friends,
  but this is not enterprise authentication; use passwords you don't use elsewhere.
- Free tiers sleep: Streamlit apps nap after a period of inactivity (a click wakes them), and free Supabase
  projects can be paused after long inactivity (resume from its dashboard). Data is kept.
- Backups: in Supabase use the Table editor → export to CSV occasionally, especially before the end of a block.
- The grade "projected final" counts empty items as 0 until you enter a grade or a what-if.

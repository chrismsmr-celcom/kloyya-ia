
🚀 Kloyya — AI-Powered Outcome Engine
Kloyya is an AI-powered platform that turns plain-language outcomes into actionable insights. You state what you want to be true, Kloyya reads across your connected tools (Slack, Gmail, Salesforce, etc.), reasons through the data, and delivers answers with citations and confidence scores.

📦 Tech Stack
Frontend
HTML + CSS + JavaScript (Single-page prototype)

Deployed on Vercel (static hosting)

Backend
FastAPI (Python) — REST API + SSE

Supabase — PostgreSQL + Auth + Storage

LiteLLM — Multi-provider LLM routing (OpenAI, Anthropic, Perplexity, etc.)

Composio — 14+ tool integrations

Deployed on Vercel (Serverless Functions)

Infrastructure
Vercel — Frontend + API hosting

Supabase — Database + Auth + Storage

Upstash — Redis (for background jobs, optional)

QStash / Railway — Background workers (for long-running tasks)

📁 Project Structure
text
kloyya-app/
├── frontend/                 # Static HTML prototype
│   ├── index.html
│   └── Kloyya-prototype.html
│
├── api/                      # Vercel serverless entry point
│   └── index.py
│
├── app/                      # FastAPI application
│   ├── __init__.py
│   ├── main.py               # App factory
│   ├── config.py             # Settings from .env
│   ├── deps.py               # Dependencies (auth, DB)
│   ├── core/                 # Core modules
│   │   ├── security.py       # JWT validation
│   │   └── enums.py          # Shared enums
│   ├── db/                   # Database
│   │   └── session.py        # Connection pool
│   ├── models/               # Pydantic schemas
│   │   └── schemas.py
│   ├── routers/              # API routes
│   │   ├── outcomes.py
│   │   ├── connections.py
│   │   ├── memory.py
│   │   ├── impact.py
│   │   ├── documents.py
│   │   ├── onboarding.py
│   │   └── billing.py
│   └── services/             # Business logic
│       ├── llm_router.py
│       ├── composio_service.py
│       ├── rag_service.py
│       ├── run_engine.py
│       ├── transcription.py
│       └── entitlements.py
│
├── sql/                      # Supabase schema
│   ├── 001_init_schema.sql
│   ├── 002_rls_schema.sql
│   └── 003_pgvector_rag.sql
│
├── frontend-bridge/          # JS client for frontend
│   ├── api-client.js
│   └── integration.md
│
├── vercel.json               # Vercel configuration
├── package.json              # Vercel build script
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variables template
├── .vercelignore             # Files ignored by Vercel
└── README.md                 # This file
🚀 Deployment Instructions
Prerequisites
Supabase account (free tier)

Vercel account (free tier)

API Keys for your LLM providers (OpenAI, Anthropic, etc.)

Composio API key

Step 1: Clone & Setup
bash
git clone https://github.com/your-username/kloyya-app.git
cd kloyya-app
Step 2: Configure Supabase
Create a new project on Supabase

Run the SQL scripts in order:

sql/001_init_schema.sql

sql/002_rls_schema.sql

sql/003_pgvector_rag.sql

Step 3: Environment Variables
Copy .env.example to .env and fill in your values:

bash
cp .env.example .env
Required variables:

Variable	Description
SUPABASE_URL	Your Supabase project URL
SUPABASE_ANON_KEY	Supabase anonymous key
SUPABASE_SERVICE_ROLE_KEY	Supabase service role key
SUPABASE_JWT_SECRET	JWT secret from Supabase
DATABASE_URL	PostgreSQL connection string
OPENAI_API_KEY	OpenAI API key
ANTHROPIC_API_KEY	Anthropic API key (optional)
COMPOSIO_API_KEY	Composio API key
Step 4: Deploy to Vercel
Push your code to GitHub

Go to Vercel

Click "Add New Project"

Import your GitHub repository

Vercel will auto-detect vercel.json

Add all environment variables from .env

Click "Deploy"

🔧 Local Development
Backend
bash
# Install dependencies
pip install -r requirements.txt

# Run locally
uvicorn app.main:app --reload
Frontend
Simply open frontend/index.html in your browser, or serve with:

bash
# Using Python
python -m http.server 5500 --directory frontend

# Or with Vercel CLI
vercel dev
🗑️ Files Removed for Vercel
The following files are removed because they are incompatible with Vercel serverless:

File	Reason
dockerfile.txt	Vercel doesn't use Docker
docker-compose.yml	Vercel doesn't use Docker Compose
scripts/worker.py	Long-running workers don't work on Vercel
app/core/sse.py	SSE has 10s timeout on Vercel Hobby
app/services/patchright_service.py	Playwright requires a browser
For long-running tasks:
Use Upstash QStash or Vercel Cron Jobs

Or deploy the worker separately on Railway/Render

📝 API Documentation
Once deployed, the API is available at:

text
https://your-app.vercel.app/api
Swagger UI is available at:

text
https://your-app.vercel.app/docs
Main Endpoints
Method	Endpoint	Description
POST	/api/outcomes	Create a new outcome
GET	/api/outcomes	List all outcomes
GET	/api/outcomes/:id	Get outcome details
GET	/api/outcomes/:id/plan	Get the plan steps
POST	/api/outcomes/:id/run	Start execution
GET	/api/connections	List all tool connections
GET	/api/memory	List workspace memory
GET	/api/impact	Dashboard metrics
🧠 How It Works
User states an outcome → POST /api/outcomes

Kloyya clarifies → Asks one smart question back

Plan is generated → Multi-step plan with sources

User edits plan → Can add/remove steps

Run executes → Reads across tools, reasons, delivers answer

Approval gate → Any write action pauses for human approval

🔐 Security
RLS enforced at database level

JWT validation via Supabase

Read-only by default for all tool connections

Write scope requested per outcome, expires with outcome

Audit log tracks all sensitive actions

📦 Dependencies
Python
See requirements.txt for full list.

Key packages:

fastapi — API framework

supabase — Supabase client

litellm — LLM routing

composio-core — Tool integrations

asyncpg — PostgreSQL driver

stripe — Payment processing

Frontend
No build tools required

Vanilla HTML + CSS + JS

🛠️ Future Improvements
□ Add WebSocket support (via Pusher or Upstash)
□ Background worker on Railway
□ File upload improvements
□ Better error handling
□ Unit tests
□ CI/CD pipeline
📄 License
Copyright © 2026 Kloyya Ltd. All rights reserved.

🙏 Credits
Built with ❤️ using FastAPI, Supabase, Vercel, and the power of LLMs.

Made with 🔥 by the Kloyya team


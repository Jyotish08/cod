# Online Judge Platform Foundation

The project includes the normalized problem database, Pydantic contracts,
repository adapter, local Python executor, plugin socket, and FastAPI API.

Install backend dependencies from the repository root:

```powershell
python -m pip install -r requirements.txt
```

Start the backend in one terminal:

```powershell
python -m uvicorn app:app --reload
```

Install and start the frontend in another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Set `OJ_DATABASE_URL` to select another SQLAlchemy database URL. The default
is `sqlite:///oj_platform.db`.

The API exposes `/api/health`, `/api/problems`, `/api/problems/{slug_or_id}`,
`/api/problems/{problem_id}/submissions`, `/api/stats`, and `/api/execute`.
Set `VITE_USE_MOCK=true` before `npm run dev` to use the mock adapter offline.
The local executor applies a restricted Python namespace
and process timeouts for development. It is not an OS-level sandbox for
untrusted public submissions; deploy external submissions behind a hardened
container or equivalent isolation boundary.

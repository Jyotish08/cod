"""FastAPI application exposing the problem catalog and local judge."""
import os
from datetime import datetime, timezone
from calendar import monthrange
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import cast, func, or_, select, text, desc, asc, String
from sqlalchemy.dialects.postgresql import JSONB

from core.adapters.local_python_executor import LocalPythonSubprocessExecutor
from core.adapters.plugins.ast_metrics_plugin import ASTMetricsPlugin
from core.contracts import (Difficulty, ExecutionRequestDTO, ExecutionResponseDTO,
                            ProblemSummaryDTO, ProblemWorkspaceDTO, SubmissionHistoryDTO)
from core.database import Base, make_engine, make_session_factory
from core.models import Problem, UserProblemStatus, UserStats, StudyPlan, SubmissionModel
from core.ports.plugin_port import PluginRegistry
from core.ports.problem_repository import SqlAlchemyProblemRepository


def create_app(database_url: Optional[str] = None) -> FastAPI:
    url = database_url or os.environ.get("OJ_DATABASE_URL", "sqlite:///oj_platform.db")
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    # Additive SQLite migration for databases created before dashboard support.
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(problems)")}
            for name, sql in (("number", "INTEGER NOT NULL DEFAULT 0"),
                              ("acceptance_rate", "FLOAT NOT NULL DEFAULT 0"),
                              ("frequency", "VARCHAR(16) NOT NULL DEFAULT 'Medium'")):
                if name not in columns:
                    conn.exec_driver_sql(f"ALTER TABLE problems ADD COLUMN {name} {sql}")
            conn.exec_driver_sql("UPDATE problems SET number=id WHERE number=0")
    sessions = make_session_factory(engine)
    executor = LocalPythonSubprocessExecutor()
    plugins = PluginRegistry()
    plugins.register(ASTMetricsPlugin())

    @asynccontextmanager
    async def lifespan(_api):
        yield
        engine.dispose()

    api = FastAPI(title="Online Judge Platform", version="1.0.0", lifespan=lifespan)
    api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"])
    api.state.engine = engine
    api.state.sessions = sessions
    api.state.executor = executor
    api.state.plugins = plugins

    @api.get("/api/dashboard")
    def dashboard(user_id: str = "local-user", status: str = "all", search: str = "",
                  difficulty: str = "", topic: str = "", frequency: str = "",
                  sort: str = "number", direction: str = "asc", page: int = 1, page_size: int = 10):
        """Dashboard aggregate, focus and server-filtered problem page for the current user."""
        page = max(1, page); page_size = max(1, min(page_size, 100))
        with sessions() as session:
            stats = session.get(UserStats, user_id)
            if not stats:
                stats = UserStats(user_id=user_id)
                session.add(stats)
                session.flush()
            plan = session.scalar(select(StudyPlan).where(StudyPlan.user_id == user_id,
                                                           StudyPlan.is_active.is_(True)))
            if not plan:
                plan = StudyPlan(user_id=user_id)
                session.add(plan); session.flush()
            # Reconcile old judge submissions into this local dashboard's status rows.
            grouped = session.execute(select(SubmissionModel.problem_id,
                func.max(SubmissionModel.created_at), func.max(SubmissionModel.overall_verdict == "AC"))
                .where(SubmissionModel.mode == "submit").group_by(SubmissionModel.problem_id)).all()
            for pid, attempted, solved in grouped:
                row = session.scalar(select(UserProblemStatus).where(
                    UserProblemStatus.user_id == user_id, UserProblemStatus.problem_id == pid))
                if not row:
                    row = UserProblemStatus(user_id=user_id, problem_id=pid)
                    session.add(row)
                row.status = "Solved" if solved else "In Progress"
                row.last_attempted_at = attempted
            session.flush()
            base = select(Problem).outerjoin(UserProblemStatus, (UserProblemStatus.problem_id == Problem.id) &
                 (UserProblemStatus.user_id == user_id))
            def status_clause(value):
                if value == "solved": return UserProblemStatus.status == "Solved"
                if value == "in_progress": return UserProblemStatus.status == "In Progress"
                if value == "todo": return or_(UserProblemStatus.status.is_(None), UserProblemStatus.status == "Not started")
                return None
            filters = []
            sc = status_clause(status)
            if sc is not None: filters.append(sc)
            if search:
                pattern = f"%{search}%"
                filters.append(or_(Problem.title.ilike(pattern), Problem.number.cast(String).ilike(pattern)))
            if difficulty: filters.append(Problem.difficulty == difficulty.upper())
            if frequency: filters.append(Problem.frequency == frequency)
            if topic:
                tags = func.json_each(Problem.tags).table_valued("key", "value").alias("dashboard_tags")
                filters.append(select(1).select_from(tags).where(tags.c.value == topic).exists())
            order_col = {"acceptance": Problem.acceptance_rate, "difficulty": Problem.difficulty,
                         "frequency": Problem.frequency, "number": Problem.number}.get(sort, Problem.number)
            total = session.scalar(select(func.count()).select_from(base.where(*filters).subquery())) or 0
            stmt = base.where(*filters).order_by((desc if direction == "desc" else asc)(order_col), Problem.number)
            problems = session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
            statuses = {row.problem_id: row for row in session.scalars(select(UserProblemStatus).where(
                UserProblemStatus.user_id == user_id, UserProblemStatus.problem_id.in_([p.id for p in problems]))).all()}
            solved_count = session.scalar(select(func.count()).select_from(UserProblemStatus).where(
                UserProblemStatus.user_id == user_id, UserProblemStatus.status == "Solved")) or 0
            submissions = session.scalar(select(func.count()).select_from(SubmissionModel).where(
                SubmissionModel.mode == "submit")) or 0
            accepted = session.scalar(select(func.count()).select_from(SubmissionModel).where(
                SubmissionModel.mode == "submit", SubmissionModel.overall_verdict == "AC")) or 0
            counts = {}
            for name, clause in (("solved", UserProblemStatus.status == "Solved"),
                                 ("in_progress", UserProblemStatus.status == "In Progress")):
                counts[name] = session.scalar(select(func.count()).select_from(UserProblemStatus).where(
                    UserProblemStatus.user_id == user_id, clause)) or 0
            counts["all"] = session.scalar(select(func.count()).select_from(Problem)) or 0
            counts["todo"] = max(0, counts["all"] - counts["solved"] - counts["in_progress"])
            focus = session.scalar(select(Problem).join(UserProblemStatus).where(
                UserProblemStatus.user_id == user_id, UserProblemStatus.status == "In Progress")
                .order_by(UserProblemStatus.last_attempted_at.desc()))
            if not focus:
                rec_ids = plan.recommended_problem_ids or []
                focus = session.get(Problem, rec_ids[0]) if rec_ids else None
            if not focus:
                focus = session.scalar(select(Problem).where(Problem.difficulty != "UNKNOWN").order_by(Problem.number))
            daily = session.scalar(select(Problem).where(Problem.difficulty != "UNKNOWN")
                .order_by(Problem.number).offset(datetime.now(timezone.utc).date().toordinal() % max(1, session.scalar(
                    select(func.count()).select_from(Problem).where(Problem.difficulty != "UNKNOWN")) or 1)).limit(1))
            total_problems = counts["all"]
            total_pages = max(1, (total + page_size - 1) // page_size)
            today = datetime.now(timezone.utc).date()
            weekly = stats.weekly_activity or {}
            topic_values = stats.topic_mastery or {"Array": 80, "String": 60, "Linked List": 50, "Math": 50, "Binary Search": 40}
            def encode(p):
                st = statuses.get(p.id)
                return {"id": p.id, "number": p.number or p.id, "title": p.title, "slug": p.slug,
                    "difficulty": p.difficulty.title() if p.difficulty in ("EASY", "MEDIUM", "HARD") else "Medium",
                    "topics": p.tags or [], "acceptance_rate": p.acceptance_rate or 0,
                    "frequency": p.frequency or "Medium", "status": st.status if st else "Not started",
                    "is_bookmarked": bool(st and st.is_bookmarked)}
            focus_status = session.scalar(select(UserProblemStatus).where(UserProblemStatus.user_id == user_id,
                UserProblemStatus.problem_id == focus.id)) if focus else None
            session.commit()
            return {"summary": {"solved": solved_count, "acceptance": round(accepted * 100 / submissions, 1) if submissions else 0,
                    "streak": stats.streak_days, "monthly_goal_target": stats.monthly_goal_target,
                    "monthly_goal_current": stats.monthly_goal_current or solved_count,
                    "activity": weekly, "topics": topic_values,
                    "plan": {"title": plan.title, "topic_progress": plan.topic_progress or {"completed": 3, "total": 10}}},
                "focus": encode(focus) if focus else None, "focus_time": focus_status.time_spent_minutes if focus_status else 18,
                "challenge": encode(daily) if daily else None, "counts": counts,
                "problems": [encode(p) for p in problems], "total": total, "page": page, "page_size": page_size,
                "total_pages": total_pages, "today": today.isoformat(), "problem_count": total_problems}

    @api.patch("/api/problems/{problem_id}/bookmark")
    def toggle_bookmark(problem_id: int, is_bookmarked: bool, user_id: str = "local-user"):
        with sessions() as session:
            if not session.get(Problem, problem_id): raise HTTPException(status_code=404, detail="Problem not found")
            row = session.scalar(select(UserProblemStatus).where(UserProblemStatus.user_id == user_id,
                UserProblemStatus.problem_id == problem_id))
            if not row:
                row = UserProblemStatus(user_id=user_id, problem_id=problem_id)
                session.add(row)
            row.is_bookmarked = is_bookmarked
            session.commit()
            return {"id": problem_id, "is_bookmarked": row.is_bookmarked}

    @api.get("/api/health")
    def health():
        try:
            with sessions() as session:
                session.execute(text("SELECT 1"))
                total = session.scalar(select(func.count()).select_from(Problem)) or 0
                ready = session.scalar(select(func.count()).select_from(Problem).where(
                    Problem.ingestion_status == "COMPLETE")) or 0
            return {"status": "ok", "database": "connected", "total_problems": total,
                    "ready_to_solve": ready}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")

    @api.get("/api/problems", response_model=List[ProblemSummaryDTO])
    def list_problems(difficulty: Optional[Difficulty] = None, tag: Optional[str] = None,
                      search: Optional[str] = None, only_complete: bool = True,
                      limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        with sessions() as session:
            stmt = select(Problem).order_by(Problem.id)
            if difficulty:
                stmt = stmt.where(Problem.difficulty == difficulty.value)
            if only_complete:
                stmt = stmt.where(Problem.ingestion_status == "COMPLETE")
            if search:
                pattern = f"%{search}%"
                stmt = stmt.where(or_(Problem.title.ilike(pattern), Problem.slug.ilike(pattern)))
            if tag:
                if session.bind.dialect.name == "sqlite":
                    values = func.json_each(Problem.tags).table_valued("key", "value").alias("tag_values")
                    stmt = stmt.where(select(1).select_from(values).where(values.c.value == tag).exists())
                else:
                    stmt = stmt.where(cast(Problem.tags, JSONB).contains([tag]))
            rows = session.scalars(stmt.offset(offset).limit(limit)).all()
            statuses = SqlAlchemyProblemRepository(session)._submission_statuses([p.id for p in rows])
            return [ProblemSummaryDTO(id=p.id, slug=p.slug, title=p.title,
                difficulty=p.difficulty, tags=p.tags or [],
                is_ready_to_solve=bool(p.has_sample_tests and p.has_starter_code),
                user_status=statuses.get(p.id, "UNSOLVED")) for p in rows]

    @api.get("/api/problems/{slug_or_id}", response_model=ProblemWorkspaceDTO)
    def get_workspace(slug_or_id: str):
        with sessions() as session:
            try:
                return SqlAlchemyProblemRepository(session).get_workspace_problem(slug_or_id)
            except LookupError:
                raise HTTPException(status_code=404, detail="Problem not found")

    @api.get("/api/problems/{problem_id}/submissions", response_model=List[SubmissionHistoryDTO])
    def get_problem_submissions(problem_id: int, limit: int = Query(20, ge=1, le=100)):
        with sessions() as session:
            if session.get(Problem, problem_id) is None:
                raise HTTPException(status_code=404, detail="Problem not found")
            return SqlAlchemyProblemRepository(session).get_problem_submissions(problem_id, limit)

    @api.get("/api/stats")
    def get_stats():
        with sessions() as session:
            return SqlAlchemyProblemRepository(session).get_user_stats()

    @api.post("/api/execute", response_model=ExecutionResponseDTO)
    def execute(request: ExecutionRequestDTO):
        with sessions() as session:
            try:
                problem = SqlAlchemyProblemRepository(session).get_judge_payload(request.problem_id)
            except LookupError:
                raise HTTPException(status_code=404, detail="Problem not found")
        # This synchronous endpoint is dispatched by FastAPI into its worker
        # pool, keeping subprocess.run off the ASGI event loop.
        response = executor.execute(problem, request)
        plugins.dispatch(problem, request, response)
        if request.mode == "submit":
            with sessions() as session:
                SqlAlchemyProblemRepository(session).record_submission(request, response)
        return response

    return api


app = create_app()

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillRequirement:
    name: str
    category: str
    importance: str = "required"
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RoleBenchmark:
    title: str
    company_type: str
    summary: str
    requirements: tuple[SkillRequirement, ...]
    responsibilities: tuple[str, ...]
    provider: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    updated_at: str = ""
    source_kind: str = "benchmark"


SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "FastAPI": ("fastapi",),
    "Flask": ("flask",),
    "Django": ("django",),
    "SQL": ("sql",),
    "PostgreSQL": ("postgresql", "postgres"),
    "SQLite": ("sqlite",),
    "SQLAlchemy": ("sqlalchemy",),
    "REST APIs": ("rest api", "rest apis", "restful", "api development"),
    "Async Python": ("asyncio", "async python", "asynchronous python"),
    "HTTPX": ("httpx",),
    "BeautifulSoup": ("beautifulsoup", "beautiful soup", "bs4"),
    "Playwright": ("playwright",),
    "HTML Parsing": ("html parsing", "web scraping", "scraping", "parser"),
    "JavaScript": ("javascript", "js"),
    "TypeScript": ("typescript", "ts"),
    "React": ("react", "react.js", "reactjs"),
    "Next.js": ("next.js", "nextjs"),
    "HTML": ("html",),
    "CSS": ("css",),
    "HTMX": ("htmx",),
    "Tailwind": ("tailwind", "tailwindcss"),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    "AWS": ("aws", "amazon web services"),
    "GCP": ("gcp", "google cloud"),
    "Azure": ("azure",),
    "Redis": ("redis",),
    "Celery": ("celery",),
    "APScheduler": ("apscheduler",),
    "Git": ("git", "gitlab"),
    "CI/CD": ("ci/cd", "github actions", "gitlab ci", "continuous integration"),
    "Testing": ("testing", "unit tests", "integration tests", "pytest", "unittest"),
    "Pytest": ("pytest",),
    "Pandas": ("pandas",),
    "NumPy": ("numpy",),
    "scikit-learn": ("scikit-learn", "sklearn"),
    "Data Visualization": ("data visualization", "dashboards", "charts", "plotly"),
    "Power BI": ("power bi", "powerbi"),
    "Tableau": ("tableau",),
    "Excel": ("excel", "spreadsheets"),
    "ETL": ("etl", "data pipeline", "data pipelines"),
    "Statistics": ("statistics", "statistical analysis"),
    "Machine Learning": ("machine learning", "ml"),
    "Deep Learning": ("deep learning", "neural networks", "pytorch", "tensorflow"),
    "PyTorch": ("pytorch",),
    "Forecasting": ("forecasting", "time series", "time-series"),
    "LLM": ("llm", "large language model", "large language models"),
    "RAG": ("rag", "retrieval augmented generation", "vector search"),
    "Prompt Engineering": ("prompt engineering", "prompting"),
    "Vector Databases": ("vector database", "vector databases", "pinecone", "qdrant", "weaviate"),
    "NLP": ("nlp", "natural language processing"),
    "Monitoring": ("monitoring", "observability", "prometheus", "grafana"),
    "Terraform": ("terraform",),
    "Linux": ("linux", "unix"),
    "Product Analytics": ("product analytics", "funnels", "retention", "cohort analysis"),
}


def req(name: str, category: str, importance: str = "required") -> SkillRequirement:
    return SkillRequirement(
        name=name,
        category=category,
        importance=importance,
        aliases=SKILL_ALIASES.get(name, (name.lower(),)),
    )


ROLE_BENCHMARKS: tuple[RoleBenchmark, ...] = (
    RoleBenchmark(
        title="ML Engineer",
        company_type="Machine learning product team",
        summary="Builds, evaluates, and ships machine learning models into usable product workflows.",
        requirements=(
            req("Python", "language"),
            req("Machine Learning", "ai"),
            req("SQL", "data"),
            req("Statistics", "analytics"),
            req("Pandas", "data", "preferred"),
            req("NumPy", "data", "preferred"),
            req("scikit-learn", "ai", "preferred"),
            req("PyTorch", "ai", "preferred"),
            req("Deep Learning", "ai", "nice_to_have"),
            req("Data Visualization", "analytics", "nice_to_have"),
            req("Forecasting", "ai", "nice_to_have"),
            req("Git", "workflow", "nice_to_have"),
        ),
        responsibilities=(
            "train and evaluate machine learning models",
            "prepare datasets and features",
            "communicate model performance and tradeoffs",
            "ship ML outputs into product or analytical workflows",
        ),
    ),
    RoleBenchmark(
        title="Backend Python Engineer",
        company_type="API-first SaaS",
        summary="Builds production APIs, database-backed services, tests, and integrations.",
        requirements=(
            req("Python", "language"),
            req("REST APIs", "backend"),
            req("SQL", "data"),
            req("Git", "workflow"),
            req("Testing", "quality"),
            req("FastAPI", "backend", "preferred"),
            req("PostgreSQL", "data", "preferred"),
            req("SQLAlchemy", "data", "preferred"),
            req("Docker", "platform", "preferred"),
            req("Async Python", "backend", "preferred"),
            req("Redis", "platform", "nice_to_have"),
            req("CI/CD", "workflow", "nice_to_have"),
        ),
        responsibilities=(
            "design and maintain API endpoints",
            "write tests for backend behavior",
            "work with relational databases",
            "integrate external services",
        ),
    ),
    RoleBenchmark(
        title="Full-Stack Python Developer",
        company_type="Product engineering team",
        summary="Connects Python services with a practical, user-facing web interface.",
        requirements=(
            req("Python", "language"),
            req("JavaScript", "frontend"),
            req("HTML", "frontend"),
            req("CSS", "frontend"),
            req("SQL", "data"),
            req("Git", "workflow"),
            req("FastAPI", "backend", "preferred"),
            req("React", "frontend", "preferred"),
            req("HTMX", "frontend", "preferred"),
            req("PostgreSQL", "data", "preferred"),
            req("Docker", "platform", "nice_to_have"),
            req("Testing", "quality", "nice_to_have"),
        ),
        responsibilities=(
            "ship full-stack product features",
            "build forms, dashboards, and UI states",
            "connect frontend workflows to backend APIs",
            "maintain database-backed application logic",
        ),
    ),
    RoleBenchmark(
        title="AI Product Engineer",
        company_type="LLM-enabled product",
        summary="Builds user-facing features that combine product UX, APIs, and LLM workflows.",
        requirements=(
            req("Python", "language"),
            req("LLM", "ai"),
            req("REST APIs", "backend"),
            req("Git", "workflow"),
            req("FastAPI", "backend", "preferred"),
            req("RAG", "ai", "preferred"),
            req("Prompt Engineering", "ai", "preferred"),
            req("Vector Databases", "ai", "preferred"),
            req("NLP", "ai", "nice_to_have"),
            req("Testing", "quality", "nice_to_have"),
            req("Product Analytics", "product", "nice_to_have"),
        ),
        responsibilities=(
            "integrate LLM APIs into product workflows",
            "evaluate output quality and failure modes",
            "build interfaces around AI-assisted recommendations",
            "track cost and quality of model calls",
        ),
    ),
    RoleBenchmark(
        title="Data Analyst",
        company_type="Operations and product analytics",
        summary="Turns datasets into decisions through SQL, analysis, and clear reporting.",
        requirements=(
            req("SQL", "data"),
            req("Excel", "data"),
            req("Data Visualization", "analytics"),
            req("Statistics", "analytics"),
            req("Pandas", "data", "preferred"),
            req("Python", "language", "preferred"),
            req("Tableau", "analytics", "preferred"),
            req("Power BI", "analytics", "preferred"),
            req("ETL", "data", "nice_to_have"),
            req("Product Analytics", "product", "nice_to_have"),
        ),
        responsibilities=(
            "analyze business or product metrics",
            "build dashboards and recurring reports",
            "write SQL queries for datasets",
            "communicate findings to stakeholders",
        ),
    ),
    RoleBenchmark(
        title="Automation and Scraping Engineer",
        company_type="Workflow automation team",
        summary="Builds compliant data collection, parsing, and automation pipelines.",
        requirements=(
            req("Python", "language"),
            req("HTTPX", "backend"),
            req("HTML Parsing", "scraping"),
            req("REST APIs", "backend"),
            req("Git", "workflow"),
            req("Playwright", "browser", "preferred"),
            req("BeautifulSoup", "scraping", "preferred"),
            req("FastAPI", "backend", "preferred"),
            req("APScheduler", "platform", "preferred"),
            req("Docker", "platform", "nice_to_have"),
            req("Monitoring", "platform", "nice_to_have"),
        ),
        responsibilities=(
            "collect data from allowed public sources",
            "detect failed scrapes and provider changes",
            "build retry-safe job processing",
            "surface rate limits and manual intervention states",
        ),
    ),
)

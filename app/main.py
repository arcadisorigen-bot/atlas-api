from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, text
import os

app = FastAPI(title="Atlas API", version="0.1.0")

# CORS: ajusta los orígenes cuando tengas dominio propio
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # en producción pon tu dominio/cliente
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Seguridad sencilla por API Key
API_KEY = os.getenv("API_KEY", "CAMBIA_ESTA_CLAVE")
OPEN_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/health"}

@app.middleware("http")
async def check_api_key(request: Request, call_next):
    if request.url.path in OPEN_PATHS:
        return await call_next(request)
    key = request.headers.get("x-api-key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return await call_next(request)

# DB URL desde entorno (Neon/Render) o fallback local SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///atlas.db")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}

@app.post("/init")
def init():
    ddl = """
    CREATE TABLE IF NOT EXISTS personas (
        id SERIAL PRIMARY KEY,
        nombre TEXT,
        apellido TEXT,
        alias TEXT,
        telefono TEXT,
        grupo TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_personas_telefono ON personas(telefono);
    CREATE INDEX IF NOT EXISTS idx_personas_alias ON personas(alias);
    """
    with engine.begin() as conn:
        for stmt in ddl.split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
    return {"created": True}

class PersonaIn(BaseModel):
    nombre: str | None = None
    apellido: str | None = None
    alias: str | None = None
    telefono: str | None = None
    grupo: str | None = None

@app.post("/personas")
def upsert_persona(p: PersonaIn):
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO personas (nombre, apellido, alias, telefono, grupo)
                VALUES (:nombre, :apellido, :alias, :telefono, :grupo)
            """),
            dict(nombre=p.nombre, apellido=p.apellido, alias=p.alias,
                 telefono=p.telefono, grupo=p.grupo)
        )
    return {"ok": True}

@app.get("/buscar")
def buscar(q: str = Query(..., description="Nombre/alias/teléfono")):
    sql = """
    SELECT id, nombre, apellido, alias, telefono, grupo
    FROM personas
    WHERE
      (nombre ILIKE :q OR apellido ILIKE :q OR alias ILIKE :q OR telefono ILIKE :q)
    ORDER BY id DESC
    LIMIT 50;
    """
    # En SQLite no existe ILIKE; usa LIKE case-insensitive por collation
    if DATABASE_URL.startswith("sqlite"):
        sql = """
        SELECT id, nombre, apellido, alias, telefono, grupo
        FROM personas
        WHERE
          (LOWER(COALESCE(nombre,'')) LIKE LOWER(:q)
        OR LOWER(COALESCE(apellido,'')) LIKE LOWER(:q)
        OR LOWER(COALESCE(alias,'')) LIKE LOWER(:q)
        OR LOWER(COALESCE(telefono,'')) LIKE LOWER(:q))
        ORDER BY id DESC
        LIMIT 50;
        """
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"q": f"%{q}%"}).mappings().all()
    return {"results": [dict(r) for r in rows]}

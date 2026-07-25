"""PostgreSQL session manager with bounded query execution concurrency.

The manager is intentionally small and repository-focused:
 - SQLAlchemy handles pooling
 - a bounded queue limits in-flight queries (backpressure)
 - sessions are created per call and always closed
"""

from __future__ import annotations

import queue
import re
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TypeAlias

try:
    from sqlalchemy import URL, create_engine, text
    from sqlalchemy.sql.elements import TextClause
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session, sessionmaker
except ImportError as exc:
    SQLA_ERROR = exc
    URL = create_engine = text = None  # type: ignore[assignment]
    TextClause = object
    Engine = Session = object  # type: ignore[assignment]
    sessionmaker = None  # type: ignore[assignment]
else:
    SQLA_ERROR = None

QueryText = str | TextClause
QueryParameters: TypeAlias = Mapping[str, object] | Sequence[object] | tuple[object, ...]
DbRow: TypeAlias = Mapping[str, object]
DbRows: TypeAlias = tuple[DbRow, ...]


@dataclass(frozen=True)
class DbSessionConfig:
    databaseUrl: str
    poolSize: int
    maxOverflow: int
    queryQueueSize: int
    poolTimeoutSeconds: float
    connectTimeoutSeconds: int

    @staticmethod
    def FromEnvironment() -> "DbSessionConfig":
        database_url = (
            # [07-20 설계자 확정] 분류 DB = PG* 블록(Supabase pooler).
            # 서류 작업이 ASAP_DATABASE_URL을 메인 서버 DB로 옮기면서
            # (그쪽엔 branch_decision_index·술어 테이블 없음) staged가
            # 빈손이 되는 충돌 실측 → 분류층은 PGHOST가 설정돼 있으면
            # PG* 조립 주소를 ASAP_DATABASE_URL보다 우선한다. 명시
            # 오버라이드는 ASAP_CLASSIFICATION_DATABASE_URL이다. 이 모듈은
            # .env 파일을 읽지 않으며 호출자가 셸 환경을 주입해야 한다.
            _env("ASAP_CLASSIFICATION_DATABASE_URL")
            or (_build_url_from_pg_env() if _env("PGHOST") else "")
            or _env("ASAP_DATABASE_URL")
            or _env("DATABASE_URL")
            or _build_url_from_pg_env()
        )
        fallback_pool_size = _read_optional_int_env("ASAP_DB_POOL_MAX_CONNECTIONS")
        pool_size = _read_optional_int_env("ASAP_DB_POOL_SIZE")
        if pool_size is None:
            pool_size = fallback_pool_size or 4

        return DbSessionConfig(
            databaseUrl=database_url,
            poolSize=pool_size,
            maxOverflow=_read_int_env("ASAP_DB_MAX_OVERFLOW", 8),
            queryQueueSize=_read_int_env("ASAP_DB_QUERY_QUEUE_SIZE", 8),
            poolTimeoutSeconds=float(_read_int_env("ASAP_DB_POOL_TIMEOUT_SECONDS", 30)),
            connectTimeoutSeconds=_read_int_env("ASAP_DB_CONNECT_TIMEOUT_SECONDS", 10),
        )


def _env(name: str) -> str:
    import os

    value = os.environ.get(name, "")
    if not value:
        return ""
    return value.strip()


def _read_int_env(name: str, default_value: int) -> int:
    text_value = _env(name)
    if not text_value:
        return default_value
    try:
        return int(text_value)
    except ValueError as exc:
        raise ValueError(f"환경 변수 {name}는 정수여야 합니다: {text_value}") from exc


def _read_optional_int_env(name: str) -> int | None:
    text_value = _env(name)
    if not text_value:
        return None
    try:
        return int(text_value)
    except ValueError as exc:
        raise ValueError(f"환경 변수 {name}는 정수여야 합니다: {text_value}") from exc


def _build_url_from_pg_env() -> str:
    host = _env("PGHOST")
    if not host:
        raise RuntimeError(
            "DB 연결 문자열이 없습니다. ASAP_DATABASE_URL 또는 DATABASE_URL 설정이 필요합니다."
        )

    username = _env("PGUSER")
    password = _env("PGPASSWORD")
    database_name = _env("PGDATABASE") or "postgres"
    ssl_mode = _env("PGSSLMODE")
    port_value = _env("PGPORT") or "5432"

    try:
        port = int(port_value)
    except ValueError as exc:
        raise ValueError(f"PGPORT는 정수여야 합니다: {port_value}") from exc

    # NOTE: str(URL) obscures the password as "***" in SQLAlchemy 2.x, which then
    # gets sent to the server verbatim and fails auth. render_as_string keeps it.
    return URL.create(
        "postgresql+psycopg2",
        username=username or None,
        password=password or None,
        host=host,
        port=port,
        database=database_name,
        query={"sslmode": ssl_mode} if ssl_mode else None,
    ).render_as_string(hide_password=False)


def _validate_table_name(table_name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
        raise ValueError(f"허용되지 않은 테이블명입니다: {table_name}")
    return table_name


class DbSessionManager:
    _instance: "DbSessionManager | None" = None
    _instanceLock = threading.Lock()

    def __init__(self, config: DbSessionConfig) -> None:
        if SQLA_ERROR is not None:
            raise RuntimeError(
                "SQLAlchemy가 설치되지 않았습니다. `pip install SQLAlchemy` 후 다시 시도하세요."
            ) from SQLA_ERROR
        self._config = config
        self._engine: Engine = create_engine(
            config.databaseUrl,
            pool_size=config.poolSize,
            max_overflow=config.maxOverflow,
            pool_timeout=config.poolTimeoutSeconds,
            pool_pre_ping=True,
            # [순단 내성 07-19] TCP keepalive — 원거리 DB에서 응답 패킷이
            # 유실되면 read가 영원히 블록된다(실측: 재컴파일 INSERT가
            # ClientRead 데드 커넥션으로 하루 4회, 17~37분 무한 대기).
            # keepalive가 죽은 커넥션을 ~30초 내 에러로 승격시켜 '조용한
            # 멈춤'을 재시도 가능한 실패로 바꾼다. 연결 옵션이라 판정·
            # 점수 무영향.
            connect_args={
                "connect_timeout": config.connectTimeoutSeconds,
                "keepalives": 1,
                "keepalives_idle": 10,
                "keepalives_interval": 5,
                "keepalives_count": 4,
            },
            future=True,
        )
        self._sessionFactory = sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )

        self._querySlots: "queue.Queue[object]" = queue.Queue(
            maxsize=max(config.queryQueueSize, 1)
        )
        for _ in range(max(config.queryQueueSize, 1)):
            self._querySlots.put(object())

    @classmethod
    def GetInstance(cls, config: DbSessionConfig | None = None) -> "DbSessionManager":
        if config is None:
            config = DbSessionConfig.FromEnvironment()
        with cls._instanceLock:
            if cls._instance is None or cls._instance._config != config:
                if cls._instance is not None:
                    cls._instance._engine.dispose()
                cls._instance = cls(config)
        return cls._instance

    @contextmanager
    def AcquireQuerySlot(self, timeout_seconds: float | None = None) -> Iterator[None]:
        wait_seconds = timeout_seconds if timeout_seconds is not None else 30.0
        try:
            token = self._querySlots.get(True, timeout=wait_seconds)
        except queue.Empty as exc:
            raise TimeoutError("DB query queue가 모두 점유되어 요청이 블로킹 타임아웃 되었습니다.") from exc
        try:
            yield None
        finally:
            self._querySlots.put_nowait(token)

    @contextmanager
    def OpenSession(self, timeout_seconds: float | None = None) -> Iterator[Session]:
        with self.AcquireQuerySlot(timeout_seconds):
            session = self._sessionFactory()
            try:
                yield session
                session.rollback()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

    @contextmanager
    def OpenRawConnection(self, timeout_seconds: float | None = None):
        with self.AcquireQuerySlot(timeout_seconds):
            connection = self._engine.raw_connection()
            try:
                yield connection
            finally:
                connection.close()

    def FetchRows(
        self,
        sql: QueryText,
        parameters: QueryParameters | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> DbRows:
        statement = text(sql) if isinstance(sql, str) else sql
        with self.OpenSession(timeout_seconds=timeout_seconds) as session:
            result = session.execute(statement, parameters or {})
            return tuple(
                {str(key): value for key, value in dict(row._mapping).items()}
                for row in result.fetchall()
            )

    def FetchOne(
        self,
        sql: QueryText,
        parameters: QueryParameters | None = None,
        *,
        timeout_seconds: float | None = None,
    ) -> object | None:
        with self.OpenSession(timeout_seconds=timeout_seconds) as session:
            statement = text(sql) if isinstance(sql, str) else sql
            result = session.execute(statement, parameters or {})
            return result.scalar_one_or_none()

    def TableExists(self, table_name: str) -> bool:
        safe_table = _validate_table_name(table_name)
        value = self.FetchOne(
            "SELECT to_regclass(:qualifiedName) IS NOT NULL",
            {"qualifiedName": f"public.{safe_table}"}
        )
        return bool(value)

    @property
    def Engine(self) -> Engine:
        return self._engine

"""只读 SQL 安全校验与 100 行限制。"""

from __future__ import annotations

import re


class UnsafeSQLError(ValueError):
    pass


class SQLSafetyTool:
    _dangerous = re.compile(
        r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|GRANT|REVOKE|"
        r"CREATE|REPLACE|MERGE|CALL|EXECUTE|HANDLER|LOAD|LOCK|UNLOCK)\b",
        re.IGNORECASE,
    )
    _dangerous_functions = re.compile(
        r"\b(SLEEP|BENCHMARK|LOAD_FILE)\s*\(",
        re.IGNORECASE,
    )
    _limit = re.compile(r"\bLIMIT\s+(\d+)(?:\s*,\s*(\d+))?\s*$", re.IGNORECASE)

    def __init__(self, *, max_rows: int = 100) -> None:
        self.max_rows = max_rows

    def validate(self, sql: str) -> str:
        statement = sql.strip()
        if statement.endswith(";"):
            statement = statement[:-1].rstrip()
        if not statement:
            raise UnsafeSQLError("SQL 不能为空")
        if ";" in statement:
            raise UnsafeSQLError("不允许执行多条 SQL")
        if "--" in statement or "/*" in statement or "#" in statement:
            raise UnsafeSQLError("SQL 中不允许注释")
        if not re.match(r"^(SELECT|WITH)\b", statement, re.IGNORECASE):
            raise UnsafeSQLError("仅允许 SELECT 查询")
        if not re.search(r"\bSELECT\b", statement, re.IGNORECASE):
            raise UnsafeSQLError("仅允许 SELECT 查询")
        if self._dangerous.search(statement):
            raise UnsafeSQLError("不允许执行该操作")
        if self._dangerous_functions.search(statement):
            raise UnsafeSQLError("不允许调用高风险 SQL 函数")
        if re.search(
            r"\b(INTO\s+(OUTFILE|DUMPFILE)|FOR\s+UPDATE|"
            r"INFORMATION_SCHEMA|PERFORMANCE_SCHEMA|MYSQL\.)\b",
            statement,
            re.IGNORECASE,
        ):
            raise UnsafeSQLError("不允许访问该 SQL 能力")
        return statement

    def prepare(self, sql: str) -> str:
        statement = self.validate(sql)
        match = self._limit.search(statement)
        if not match:
            return f"{statement} LIMIT {self.max_rows}"
        first = int(match.group(1))
        second = int(match.group(2)) if match.group(2) else None
        if second is None:
            if first <= self.max_rows:
                return statement
            return self._limit.sub(f"LIMIT {self.max_rows}", statement)
        if second <= self.max_rows:
            return statement
        return self._limit.sub(f"LIMIT {first}, {self.max_rows}", statement)

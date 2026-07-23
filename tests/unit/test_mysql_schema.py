"""客户画像域 MySQL 建表语句的静态约束测试。"""

import unittest

from app.dao.mysql.schema import (
    CREATE_TABLE_STATEMENTS,
    FIN_CUSTOMER_PROFILE_DDL,
    FIN_PROFILE_EVALUATION_DDL,
    render_schema_sql,
)


class MysqlSchemaTest(unittest.TestCase):
    def test_contains_tables_in_dependency_order(self) -> None:
        table_names = [
            "sys_user",
            "fin_product",
            "fin_risk_assessment",
            "fin_holdings",
            "fin_customer_profile",
            "fin_profile_evaluation",
            "fin_profile_field_audit",
            "fin_suitability_check",
        ]

        self.assertEqual(len(CREATE_TABLE_STATEMENTS), len(table_names))
        for statement, table_name in zip(
            CREATE_TABLE_STATEMENTS,
            table_names,
            strict=True,
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table_name}", statement)

    def test_profile_does_not_store_risk_score(self) -> None:
        self.assertNotIn("risk_score", FIN_CUSTOMER_PROFILE_DDL.lower())

    def test_evaluation_stores_all_scores_and_risk_levels(self) -> None:
        required_columns = (
            "d1_score",
            "d2_score",
            "d3_score",
            "d4_score",
            "total_score",
            "official_risk_level",
            "model_risk_level",
            "effective_risk_level",
        )

        for column in required_columns:
            self.assertIn(column, FIN_PROFILE_EVALUATION_DDL)

    def test_rendered_script_ends_with_newline(self) -> None:
        sql = render_schema_sql()

        self.assertTrue(sql.endswith("\n"))
        self.assertEqual(sql.count("CREATE TABLE IF NOT EXISTS"), 8)


if __name__ == "__main__":
    unittest.main()

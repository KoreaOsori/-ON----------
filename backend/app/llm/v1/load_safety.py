"""Explicit administrative CLI. No HTTP endpoint can modify source data."""
import argparse
import asyncio
from pathlib import Path

from sqlalchemy import text

from .config import Settings
from .database import create_database_engine
from .schemas import SafetyBundle


async def load(path: Path):
    bundle = SafetyBundle.model_validate_json(path.read_text(encoding="utf-8-sig"))
    engine = create_database_engine(Settings())
    try:
        async with engine.begin() as conn:
            # SQL here is bundled developer-owned DDL, never user-supplied SQL.
            for statement in Path(__file__).with_name("sql").joinpath("safety.sql").read_text().split(";"):
                if statement.strip():
                    await conn.execute(text(statement))
            run = (await conn.execute(text("SELECT status FROM product_search.ingestion_runs WHERE run_id=:run"),
                                      {"run": bundle.run_id})).scalar_one_or_none()
            if run != "complete":
                raise ValueError("완료된 vector_pipeline run_id가 필요합니다.")
            keys = {p.product_key for p in bundle.products}
            found = (await conn.execute(text("""SELECT DISTINCT product_key FROM product_search.product_links
                WHERE run_id=:run AND product_type='drug' AND product_key=ANY(CAST(:keys AS text[]))"""),
                {"run": bundle.run_id, "keys": sorted(keys)})).scalars().all()
            if keys != set(found):
                raise ValueError("해당 run에 없는 의약품 product_key가 있습니다.")
            # Immutable per run: duplicate imports fail instead of replacing published evidence.
            await conn.execute(text("""INSERT INTO llm_v1.safety_snapshot
                (run_id,rules_complete,source,code_system) VALUES (:run_id,:rules_complete,:source,:code_system)"""),
                bundle.model_dump(exclude={"products", "rules"}))
            for product in bundle.products:
                await conn.execute(text("""INSERT INTO llm_v1.product_ingredients
                    (run_id,product_key,codes,complete,source) VALUES (:run,:product_key,:codes,:complete,:source)"""),
                    {"run": bundle.run_id, **product.model_dump()})
            for rule in bundle.rules:
                await conn.execute(text("""INSERT INTO llm_v1.contraindication
                    (run_id,rule_id,left_codes,right_codes,content,conditions,source)
                    VALUES (:run,:rule_id,:left_codes,:right_codes,:content,:conditions,:source)"""),
                    {"run": bundle.run_id, **rule.model_dump()})
    finally:
        await engine.dispose()
    print(f"Imported {len(bundle.products)} products, {len(bundle.rules)} rules.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="검증된 DUR 코드 매핑 및 병용금기 JSON 적재")
    parser.add_argument("bundle", type=Path)
    asyncio.run(load(parser.parse_args().bundle))

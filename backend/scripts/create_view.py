#!/usr/bin/env python3
"""
Generate Supabase view migration from template.

Usage:
    python scripts/create_view.py \\
        --name user_active_grants_enriched \\
        --type regular \\
        --description "Eliminates N+1 in grant_service"
"""

import argparse
from datetime import datetime
from pathlib import Path

VIEW_TEMPLATE = '''-- Migration: Add {view_name} view
-- Description: {description}
-- Date: {date}
-- Type: {view_type}

-- ===== UP MIGRATION =====

-- Create {view_type} view
CREATE {materialized}VIEW {view_name} AS
{query_placeholder};

{index_placeholder}

-- Verify view
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.{table_type}
        WHERE table_schema = 'public'
          AND table_name = '{view_name}'
    ) THEN
        RAISE EXCEPTION 'View {view_name} was not created';
    END IF;
END $$;

-- ===== DOWN MIGRATION (ROLLBACK) =====

-- DROP {materialized}VIEW IF EXISTS {view_name};
{drop_index_placeholder}
-- NOTE: Uncomment above for rollback
'''

def generate_migration(name: str, view_type: str, description: str):
    """Generate migration file."""

    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{date_str}_{name}.sql"

    materialized = "MATERIALIZED " if view_type == "materialized" else ""
    table_type = "matviews" if view_type == "materialized" else "views"

    # Index placeholder for materialized views
    if view_type == "materialized":
        index_placeholder = f"""
-- Create index for fast lookups
CREATE UNIQUE INDEX idx_{name}_{{lookup_column}}
    ON {name}({{lookup_column}});
"""
        drop_index_placeholder = f"-- DROP INDEX IF EXISTS idx_{name}_{{lookup_column}};"
    else:
        index_placeholder = "-- Regular views use base table indexes"
        drop_index_placeholder = ""

    query_placeholder = """SELECT
    -- TODO: Add your query here
    t1.id,
    t1.user_id,
    t2.related_field
FROM table1 t1
JOIN table2 t2 ON t1.related_id = t2.id
WHERE t1.deleted_at IS NULL"""

    content = VIEW_TEMPLATE.format(
        view_name=name,
        view_type=view_type,
        description=description,
        date=datetime.now().strftime("%Y-%m-%d"),
        materialized=materialized,
        table_type=table_type,
        query_placeholder=query_placeholder,
        index_placeholder=index_placeholder,
        drop_index_placeholder=drop_index_placeholder
    )

    # Write to migrations directory
    migrations_dir = Path(__file__).parent.parent / "migrations"
    migrations_dir.mkdir(exist_ok=True)

    filepath = migrations_dir / filename
    filepath.write_text(content)

    print(f"✅ Created migration: {filepath}")
    print(f"\n📝 Next steps:")
    print(f"   1. Edit {filename} and replace TODO with your query")
    print(f"   2. Test with: psql -f {filepath}")
    print(f"   3. Commit migration file")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Supabase view migration")
    parser.add_argument("--name", required=True, help="View name (e.g., user_active_grants_enriched)")
    parser.add_argument("--type", choices=["regular", "materialized"], default="regular", help="View type")
    parser.add_argument("--description", required=True, help="Migration description")

    args = parser.parse_args()
    generate_migration(args.name, args.type, args.description)

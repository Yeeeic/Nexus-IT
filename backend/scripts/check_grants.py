import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def check():
    db_pass = os.getenv('NEXUS_POSTGRES_PASSWORD', '').strip()
    if not db_pass:
        raise RuntimeError('Required environment variable is missing: NEXUS_POSTGRES_PASSWORD')
    engine = create_async_engine(f'postgresql+psycopg://nexus_bootstrap:{db_pass}@postgres:5432/nexus_it')
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT grantee, privilege_type FROM information_schema.role_table_grants WHERE table_name = 'user_sessions'"))
        print('Role table grants:')
        for row in res.fetchall():
            print(' ', row)
        res2 = await conn.execute(text("SELECT grantee, column_name, privilege_type FROM information_schema.column_privileges WHERE table_name = 'user_sessions'"))
        print('Column privileges:')
        for row in res2.fetchall():
            print(' ', row)

if __name__ == '__main__':
    asyncio.run(check())

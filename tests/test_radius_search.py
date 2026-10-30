"""Distance boundaries and pagination must be established by real Postgres."""
import asyncio
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.routers.churches import router


def test_invalid_radius_requests_are_rejected_before_database_access():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    for query, status in [
        ('lat=37', 400), ('lat=37&lon=-122', 400), ('lat=37&radius_miles=10', 400),
        ('lat=91&lon=0&radius_miles=10', 422),
        ('lat=0&lon=0&radius_miles=0', 422),
        ('lat=nan&lon=0&radius_miles=10', 422),
    ]:
        assert client.get('/churches?' + query).status_code == status


@pytest.mark.skipif(not os.environ.get('DATABASE_URL'), reason='Needs isolated Postgres with all migrations')
def test_circle_crosses_city_boundary_and_orders_before_pagination():
    from psycopg import AsyncConnection
    from backend.db.repository import ChurchRepository

    async def run():
        con = await AsyncConnection.connect(os.environ['DATABASE_URL'])
        try:
            # Synthetic origin in open ocean keeps unrelated fixture rows away.
            for name, city, lat in [('radius close', 'A', 0), ('radius neighbor', 'B', .01),
                                    ('radius outside', 'A', 1), ('radius unknown', 'A', None)]:
                await con.execute('INSERT INTO churches (name, city, state, latitude, longitude) VALUES (%s,%s,%s,%s,%s)',
                                  (name, city, 'ZZ', lat, -140))
            repo = ChurchRepository(con)
            first = await repo.list_nearby(0, -140, 2, 1, 0)
            second = await repo.list_nearby(0, -140, 2, 1, 1)
            assert [first[0]['name'], second[0]['name']] == ['radius close', 'radius neighbor']
            assert len(await repo.list_nearby(0, -140, 2, 50, 0)) == 2
            assert len(await repo.list_nearby(0, -140, 1, 50, 0)) == 2
            assert (await repo.city_center('B', 'ZZ')) == {'lat': .01, 'lon': -140}
        finally:
            await con.rollback()
            await con.close()
    asyncio.run(run())

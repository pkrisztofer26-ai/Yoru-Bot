import pytest_asyncio
from native_support import creds, reset_schema, install_base

@pytest_asyncio.fixture(autouse=True)
async def native_schema(request):
    if request.node.name == "test_13_source_projection_contract":
        yield
        return
    creds()
    await reset_schema()
    await install_base()
    yield
    await reset_schema()

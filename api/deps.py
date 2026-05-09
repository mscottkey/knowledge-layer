from typing import Annotated

from fastapi import Depends

from core.config import Settings, get_settings
from graph.client import get_driver
from vector.client import get_pool


async def get_graph_client():
    return await get_driver()


async def get_vector_store():
    return await get_pool()


SettingsDep = Annotated[Settings, Depends(get_settings)]
GraphClientDep = Annotated[object, Depends(get_graph_client)]
VectorStoreDep = Annotated[object, Depends(get_vector_store)]

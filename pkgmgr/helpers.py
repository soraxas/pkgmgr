from collections.abc import AsyncIterable


async def async_all(async_iterable: AsyncIterable[object]) -> bool:
    async for element in async_iterable:
        if not element:
            return False
    return True

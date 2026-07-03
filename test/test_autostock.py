# import asyncio
#
# # from api.autostock import mcp
# from fastmcp.client import Client  # type: ignore
# from fastmcp.client.transports import FastMCPTransport  # type: ignore
#
# async def test_get_all_stock_code():
#     """测试获取所有股票代码接口及其模糊搜索功能"""
#     print("调用 get_all_stock_code():")
#     async with Client(mcp) as client:
#         result = await client.call_tool(
#             name="get_all_stock_code"
#         )
#         result = result.data
#         print(f"  获取到的股票代码总数: {len(result.get('data', []))}")
#
#         print("调用 get_all_stock_code('圣泉') (按名称搜索):")
#         result = await client.call_tool(
#             name="get_all_stock_code", arguments={"keyword": "圣泉"}
#         )
#         result = result.data
#         print(f"  搜索到的 '圣泉' 相关的股票代码数量: {len(result.get('data', []))}")
#
#
#         print("调用 get_all_stock_code('sh605589') (按代码搜索):")
#         result = await client.call_tool(
#             name="get_all_stock_code", arguments={"keyword": "sh605589"}
#         )
#         result = result.data
#         print(f"  搜索到的 '圣泉' 相关的股票代码数量: {len(result.get('data', []))}")
#
# async def test_get_all_index_code():
#     """测试获取所有指数代码接口"""
#     print("--- 测试 get_all_index_code ---")
#     async with Client(mcp) as client:
#         result = await client.call_tool(
#             name="get_all_index_code"
#         )
#         result = result.data
#         print(f"  获取到的指数代码总数: {len(result.get('data', []))}")
#     print("-" * 30)
#
#
# async def test_get_stock_industry_code():
#     """测试获取股票行业代码接口"""
#     print("--- 测试 get_stock_industry_code ---")
#     async with Client(mcp) as client:
#         result = await client.call_tool(
#             name="get_stock_industry_code"
#         )
#         result = result.data
#         print(f"  获取到的股票行业代码总数: {len(result.get('data', []))}")
#         print("-" * 30)
#
#
# async def test_get_stock_board_info():
#     """测试获取股票板块信息接口"""
#     async with Client(mcp) as client:
#         result = await client.call_tool(
#             name="get_stock_board_info"
#         )
#         result = result.data
#         print(f"  获取到的股票行业代码总数: {len(result.get('data', []))}")
#         print("-" * 30)
#
#
# async def test_get_stock_rank():
#     """测试获取股票排名接口"""
#     async with Client(mcp) as client:
#         result = await client.call_tool(
#             name="get_stock_rank", arguments={"node": "a", "pageIndex": 1}
#         )
#         result = result.data
#         print(f"  获取到的股票排名数据条数: {len(result.get('data', []))}")
#         print("-" * 30)
#
#
#
# async def test_get_stock_info():
#     """测试获取单个股票详细信息接口"""
#     async with Client(mcp) as client:
#         result = await client.call_tool(
#             name="get_stock_info", arguments={"code": "sh605589"}
#         )
#         result = result.data
#         print(f"  获取到的股票详细信息: {len(result.get('data', []))}")
#         print("-" * 30)
#
#
# async def test_get_stock_minute_data():
#     """测试获取股票分钟级别数据接口"""
#     async with Client(mcp) as client:
#         result = await client.call_tool(
#             name="get_stock_minute_data", arguments={"code": "sh605589"}
#         )
#         result = result.data
#         print(f"  获取到的股票分钟线数据条数: {len(result.get('data', []))}")
#         print("-" * 30)
#
#
# async def test_get_stock_day_kline():
#     """测试获取股票日 K 线数据接口"""
#     print("--- 测试 get_stock_day_kline (sh605589) ---")
#     async with Client(mcp) as client:
#         result = await client.call_tool(
#             name="get_stock_day_kline", arguments={"code": "sh605589", "startDate": "2025-05-01", "endDate": "2025-08-01", "type": 0}
#         )
#         result = result.data
#         print(f"  获取到的股票日 K 线数据条数 (2025-05-01 to 2025-08-01): {len(result.get('data', []))}")
#         print("-" * 30)
#
#
# async def test_get_stock_week_kline():
#     """测试获取股票周 K 线数据接口"""
#     print("--- 测试 get_stock_week_kline (sh605589) ---")
#     async with Client(mcp) as client:
#         result = await client.call_tool(
#             name="get_stock_week_kline", arguments={"code": "sh605589", "startDate": "2025-05-01", "endDate": "2025-08-01", "type": 0}
#         )
#         result = result.data
#         print(f"  获取到的股票日 K 线数据条数 (2025-05-01 to 2025-08-01): {len(result.get('data', []))}")
#         print("-" * 30)
#
#
#
# async def test_get_stock_month_kline():
#     """测试获取股票月 K 线数据接口"""
#     print("--- 测试 get_stock_month_kline (sh605589) ---")
#     async with Client(mcp) as client:
#         result = await client.call_tool(
#             name="get_stock_month_kline", arguments={"code": "sh605589", "startDate": "2025-05-01", "endDate": "2025-08-01", "type": 0}
#         )
#         result = result.data
#         print(f"  获取到的股票日 K 线数据条数 (2025-05-01 to 2025-08-01): {len(result.get('data', []))}")
#         print("-" * 30)
#
#
# # 依次调用所有测试函数
# if __name__ == "__main__":
#     asyncio.run(test_get_all_stock_code())
#     asyncio.run(test_get_all_index_code())
#     asyncio.run(test_get_stock_industry_code())
#     asyncio.run(test_get_stock_board_info())
#     asyncio.run(test_get_stock_rank())
#     asyncio.run(test_get_stock_info())
#     asyncio.run(test_get_stock_minute_data())
#     asyncio.run(test_get_stock_day_kline())
#     asyncio.run(test_get_stock_week_kline())
#     asyncio.run(test_get_stock_month_kline())
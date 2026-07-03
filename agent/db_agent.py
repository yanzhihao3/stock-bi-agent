# #  基于 数据库 进行问答： nl2sql

# import os
# os.environ["OPENAI_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# import asyncio

# from typing import Annotated
# from agents import Agent, Runner, function_tool
# from agents import set_default_openai_api, set_tracing_disabled
# set_default_openai_api("chat_completions")
# set_tracing_disabled(True)

# '''数据库解析'''
# from typing import Union
# import traceback
# from sqlalchemy import create_engine, inspect, func, select, Table, MetaData, text # ORM 框架
# import pandas as pd

# class DBParser:
#     '''DBParser 数据库的解析'''
#     def __init__(self, db_url:str) -> None:
#         '''初始化
#         db_url: 数据库链接地址
#         mysql: mysql://root:123456@localhost:3306/mydb?charset=utf8mb4
#         sqlite: sqlite://chinook.db
#         '''

#         # 判断数据库类型
#         if 'sqlite' in db_url:
#             self.db_type = 'sqlite'
#         elif 'mysql' in db_url:
#             self.db_type = 'mysql'

#         # 链接数据库
#         self.engine = create_engine(db_url, echo=False)
#         self.conn = self.engine.connect()
#         self.db_url = db_url

#         # 查看表明
#         self.inspector = inspect(self.engine)
#         self.table_names = self.inspector.get_table_names() # 获取table信息

#         self._table_fields = {} # 数据表字段
#         self.foreign_keys = [] # 数据库外键
#         self._table_sample = {} # 数据表样例

#         # 依次对每张表的字段进行统计
#         for table_name in self.table_names:
#             # print("Table ->", table_name)
#             self._table_fields[table_name] = {}

#             # 累计外键
#             self.foreign_keys += [
#                 {
#                     'constrained_table': table_name,
#                     'constrained_columns': x['constrained_columns'],
#                     'referred_table': x['referred_table'],
#                     'referred_columns': x['referred_columns'],
#                 } for x in self.inspector.get_foreign_keys(table_name)
#             ]

#             # 获取当前表的字段信息
#             table_instance = Table(table_name, MetaData(), autoload_with=self.engine)
#             table_columns = self.inspector.get_columns(table_name)
#             self._table_fields[table_name] = {x['name']:x for x in table_columns}

#             # 对当前字段进行统计
#             for column_meta in table_columns:
#                 # 获取当前字段
#                 column_instance = getattr(table_instance.columns, column_meta['name'])

#                 # 统计unique
#                 query = select(func.count(func.distinct(column_instance)))
#                 distinct_count = self.conn.execute(query).fetchone()[0]
#                 self._table_fields[table_name][column_meta['name']]['distinct'] = distinct_count

#                 # 统计most frequency value
#                 field_type = self._table_fields[table_name][column_meta['name']]['type']
#                 field_type = str(field_type)
#                 if 'text' in field_type.lower() or 'char' in field_type.lower():
#                     query = (
#                         select(column_instance, func.count().label('count'))
#                         .group_by(column_instance)
#                         .order_by(func.count().desc())
#                         .limit(1)
#                     )
#                     top1_value = self.conn.execute(query).fetchone()[0]
#                     self._table_fields[table_name][column_meta['name']]['mode'] = top1_value

#                 # 统计missing个数
#                 query = select(func.count()).filter(column_instance == None)
#                 nan_count = self.conn.execute(query).fetchone()[0]
#                 self._table_fields[table_name][column_meta['name']]['nan_count'] = nan_count

#                 # 统计max
#                 query = select(func.max(column_instance))
#                 max_value = self.conn.execute(query).fetchone()[0]
#                 self._table_fields[table_name][column_meta['name']]['max'] = max_value

#                 # 统计min
#                 query = select(func.min(column_instance))
#                 min_value = self.conn.execute(query).fetchone()[0]
#                 self._table_fields[table_name][column_meta['name']]['min'] = min_value

#                 # 任意取值
#                 query = select(column_instance).limit(10)
#                 random_value = self.conn.execute(query).all()
#                 random_value = [x[0] for x in random_value]
#                 random_value = [str(x) for x in random_value if x is not None]
#                 random_value = list(set(random_value))
#                 self._table_fields[table_name][column_meta['name']]['random'] = random_value[:3]

#             # 获取表样例（第一行）
#             query = select(table_instance)
#             self._table_sample[table_name] = pd.DataFrame([self.conn.execute(query).fetchone()])
#             self._table_sample[table_name].columns = [x['name'] for x in table_columns]

#     def get_table_fields(self, table_name) -> pd.DataFrame:
#         '''获取表字段信息'''
#         return pd.DataFrame.from_dict(self._table_fields[table_name]).T

#     def get_data_relations(self) -> pd.DataFrame:
#         '''获取数据库链接信息（主键和外键）'''
#         return pd.DataFrame(self.foreign_keys)

#     def get_table_sample(self, table_name) -> pd.DataFrame:
#         '''获取数据表样例'''
#         return self._table_sample[table_name]

#     def check_sql(self, sql: str) -> tuple[bool, str]:
#         '''通过EXPLAIN检查SQL语法和可行性（不真正执行）'''
#         try:
#             with self.engine.connect() as conn:
#                 # 只分析执行计划，不实际执行
#                 explain_sql = f"EXPLAIN {sql}"
#                 conn.execute(text(explain_sql))
#                 return True, 'ok'
#         except:
#             err_msg = traceback.format_exc()
#             return False, err_msg

#     def execute_sql(self, sql: str) -> bool:
#         '''运行SQL'''
#         with self.engine.connect() as conn:
#             res = conn.execute(text(sql))
#             return res.fetchall()


# @function_tool
# def parse_table(table_name: Annotated[str, "The table name"]) -> str:
#     """Return filed of the given table."""
#     try:
#         return parser.get_table_fields(table_name).to_markdown()
#     except:
#         # 传入的不是表名，不存在的表名
#         return ""

# # 自定义nl2sql agent
# """
# 1、没有提供合理的信息给大模型， 【帮我生成sql】
# 2、先规划、然后生成，提高sql 生成的成功率
# """
# class SQLAgent:
#     def __init__(self):
#         # 子agent，结合用户的提问，选择其中一张表回答问题，并且得到表结构（字段说明）
#         self.thinking_agent = Agent(
#             name="SQL Planer",
#             instructions="你是一个专业的SQL专家，请分析在给定的表中哪一个表可以用来回答问题。",
#             model="qwen-plus",
#             tools=[parse_table],
#         )

#         # 子agent，生成SQL
#         self.writing_agent = Agent(
#             name="SQL Writer",
#             instructions="你是一个专业的SQL专家，请根据给定的表和字段，生成一个SQL查询语句。只需要生成sql，不要有任何输出。",
#             model="qwen-plus",
#         )

#         # 子agent，结果汇总
#         self.summary_agent = Agent(
#             name="SQL Summary",
#             instructions="你是一个专业的SQL专家，基于sql执行结果，总结执行结果。先写SQL，然后总结结果",
#             model="qwen-plus",
#         )

#     async def run(self, question: str):
#         thinking_result = await Runner.run(self.thinking_agent, input=f"用户提问如下：{question}\n\n\n可选择的表格有：{parser.table_names}")

#         try:
#             table_name = thinking_result.raw_responses[0].output[0].arguments
#             table_fields = thinking_result.new_items[1].raw_item["output"]
#         except:
#             table_name = ""
#             table_fields = ""

#         writing_result = await Runner.run(self.writing_agent, input=f"用户提问如下：{question}\n\n\n可选择的表格有：{parser.table_names}, 可能选择的表格有：{table_name}\n\n\n字段有：{table_fields}")
#         print(writing_result.final_output)

#         sql = writing_result.final_output.strip()

#         if parser.check_sql(sql)[0]:
#             result = parser.execute_sql(sql)
#             summary_result = await Runner.run(self.summary_agent, input=f"用户提问如下：{question}\n\n原始SQL为：{sql}\n\nSQL结果如下：{result}")
#             print(summary_result.final_output)
#         else:
#             print(parser.check_sql(sql)[1])

#     async def run_streamed(self):
#         # 将agent 输出使用stream 方式输出
#         pass


# if __name__ == "__main__":
#     parser = DBParser('sqlite:///./chinook.db')

#     query = "数据库中总共有多少张表；"
#     print(f"\n# 原始提问: {query}")
#     asyncio.run(SQLAgent().run(query))

#     query = "员工表中有多少条记录"
#     print(f"\n# 原始提问: {query}")
#     asyncio.run(SQLAgent().run(query))

#     query = "在数据库中所有客户个数和员工个数分别是多少"
#     print(f"\n# 原始提问: {query}")
#     asyncio.run(SQLAgent().run(query))
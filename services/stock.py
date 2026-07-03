import asyncio
from typing import Optional, List

from api.autostock import get_stock_info
from models.data_models import StockFavInfo
from models.orm import UserFavoriteStockTable, SessionLocal, UserTable

# 这段代码是用户自选股功能的完整实现，包含增删查改四个核心操作。

def get_user_all_stock(user_name: str) -> List[StockFavInfo]:
    with SessionLocal() as session:
        user_id = session.query(UserTable.id).filter(UserTable.user_name == user_name).first()
        if not user_id:
            return []
        else:
            user_id = user_id[0]
        # 查询该用户的所有自选股
        user_stock_db_records = session.query(UserFavoriteStockTable).filter(UserFavoriteStockTable.user_id == user_id).all()
        # 转换为 StockFavInfo 对象列表
        return [
            StockFavInfo(
                stock_code=user_stock_db_record.stock_id,
                create_time=user_stock_db_record.create_time
            ) for user_stock_db_record in user_stock_db_records
        ]


def delete_user_stock(user_name: str, stock_code: str) -> bool:
    with SessionLocal() as session:
        user_id = session.query(UserTable.id).filter(UserTable.user_name == user_name).first()
        if not user_id:
            return False   # True 我改为False
        else:
            user_id = user_id[0]
        user_stock_db_record: UserFavoriteStockTable | None = session.query(UserFavoriteStockTable).filter(
            UserFavoriteStockTable.user_id == user_id, UserFavoriteStockTable.stock_id == stock_code).first()
        if user_stock_db_record:
            session.delete(user_stock_db_record)
            session.commit()

    return True


def add_user_stock(user_name: str, stock_code: str) -> bool:
    with SessionLocal() as session:
        user_id = session.query(UserTable.id).filter(UserTable.user_name == user_name).first()
        if not user_id:
            return False  # True 我改为False
        else:
            user_id = user_id[0]
        # 2. 检查是否已存在
        user_stock_db_record: UserFavoriteStockTable | None = session.query(UserFavoriteStockTable).filter(
            UserFavoriteStockTable.user_id == user_id, UserFavoriteStockTable.stock_id == stock_code).first()
        if user_stock_db_record:
            return False
        else:
            # 3. 创建新记录
            user_stock_db_record = UserFavoriteStockTable(
                stock_id=stock_code,
                user_id=user_id,
            )
            session.add(user_stock_db_record)
            session.commit()

            return True


def clear_user_stock(user_name: str) -> bool:
    with SessionLocal() as session:
        user_id = session.query(UserTable.id).filter(UserTable.user_name == user_name).first()
        if not user_id:
            return False # True 我改为False
        else:
            user_id = user_id[0]
        # 批量删除该用户的所有自选股
        session.query(UserFavoriteStockTable).filter(UserFavoriteStockTable.user_id == user_id).delete()
        session.commit()
        return True

from datetime import datetime
from typing import Optional, List, Dict, Literal, Union, Any
from pydantic import BaseModel, Field, conint

# 这段代码是数据模型定义文件，使用 Pydantic 来定义所有 API 请求和响应的数据结构

class User(BaseModel):
    user_id: int
    user_name: str
    user_role: str
    register_time: datetime
    status: bool

class BasicResponse(BaseModel):
    code: int  # 状态码（0=成功）
    message: str
    data : Optional[Union[List[Any], Any]]  # 响应数据（可以是任何类型）

class RequestForUserLogin(BaseModel):
    user_name: str
    password: str

class RequestForUserRegister(BaseModel):
    user_name: str
    password: str
    user_role: str

class RequestForUserResetPassword(BaseModel):
    user_name: str
    password: str
    new_password: str

class RequestForUserChangeInfo(BaseModel):
    user_name: str
    user_role: Optional[str]
    status: Optional[bool]

# 用户在对话，传入的信息  聊天请求（核心）
class RequestForChat(BaseModel):
    # 基础字段
    content: str = Field(..., description="用户的提问")
    user_name: str = Field(..., description="用户名")
    session_id: Optional[str] = Field(None, description="对话session_id, 获取对话上下文")
    task: Optional[str] = Field(None, description="对话任务")
    tools: Optional[List[str]] = Field(None, description="可选的工具列表")

    # 后序可以持续增加，用户输入图、上传文件、链接、音频、视频，复杂的解析
    image_content: Optional[str] = Field(None)
    file_content: Optional[str] = Field(None)
    url_content: Optional[str] = Field(None)
    audio_content: Optional[str] = Field(None)
    video_content: Optional[str] = Field(None)

    # 后序可以持续增加，对话模型
    vison_mode: Optional[bool] = Field(False) # 视觉模式
    deepsearch_mode: Optional[bool] = Field(False) # 深度搜索
    sql_interpreter: Optional[bool] = Field(False) # SQL解释器
    code_interpreter: Optional[bool] = Field(False) # 代码解释器

class ResponseForChat(BaseModel):
    response_text: str
    session_id: Optional[str] = Field(None)
    response_code: Optional[str] =  Field(None)
    response_sql: Optional[str] =  Field(None)

class StockFavInfo(BaseModel):
    stock_code: str
    create_time: datetime


class ChatSession(BaseModel):
    user_id: int
    session_id: str
    title: str
    start_time: datetime
    feedback: Optional[bool] = Field(None)
    feedback_time: Optional[datetime] = Field(None)


# ==================== Json Schema 统一响应模型 ====================
# 目的：实现 API 响应统一 Schema 规范化，大模型友好结构化上下文供给

class StockCodeItem(BaseModel):
    """股票代码信息"""
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    market: Optional[str] = Field(None, description="市场")


class StockInfoItem(BaseModel):
    """股票详细信息"""
    code: str
    name: str
    open: Optional[float] = Field(None, description="开盘价")
    close: Optional[float] = Field(None, description="收盘价")
    high: Optional[float] = Field(None, description="最高价")
    low: Optional[float] = Field(None, description="最低价")
    volume: Optional[float] = Field(None, description="成交量")
    turnover: Optional[float] = Field(None, description="成交额")
    pe: Optional[float] = Field(None, description="市盈率")
    market_cap: Optional[float] = Field(None, description="总市值")


class KLineItem(BaseModel):
    """K线数据项"""
    date: str = Field(..., description="日期")
    open: float = Field(..., description="开盘价")
    close: float = Field(..., description="收盘价")
    high: float = Field(..., description="最高价")
    low: float = Field(..., description="最低价")
    volume: float = Field(..., description="成交量")
    turnover: Optional[float] = Field(None, description="成交额")


class IndustryRankItem(BaseModel):
    """行业板块排行项"""
    code: str = Field(..., description="板块代码")
    name: str = Field(..., description="板块名称")
    change: Optional[float] = Field(None, description="涨跌幅")
    volume: Optional[float] = Field(None, description="成交量")
    lead_stock: Optional[str] = Field(None, description="领涨股票")


class NewsItem(BaseModel):
    """新闻条目"""
    title: str = Field(..., description="标题")
    content: Optional[str] = Field(None, description="内容")
    source: Optional[str] = Field(None, description="来源")
    publish_time: Optional[str] = Field(None, description="发布时间")


class WeatherItem(BaseModel):
    """天气信息"""
    city: str = Field(..., description="城市")
    weather: str = Field(..., description="天气状态")
    temperature: str = Field(..., description="温度")
    humidity: Optional[str] = Field(None, description="湿度")
    wind: Optional[str] = Field(None, description="风力")


class ApiResponse(BaseModel):
    """统一 API 响应格式"""
    code: int = Field(200, description="状态码，200=成功")
    message: str = Field("success", description="状态信息")
    data: Optional[Any] = Field(None, description="响应数据")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat(), description="响应时间戳")
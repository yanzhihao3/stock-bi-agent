from fastapi import FastAPI, APIRouter
from typing import Union

router = APIRouter(prefix="/v1/data", tags=["data"])

# /v1/data/download
@router.post("/download")
async def download_data():
    pass

# /v1/data/create
@router.post("/create")
async def create_data():
    pass

@router.post("/upload")
async def upload_data():
    pass

@router.post("/delete")
async def delete_data():
    pass
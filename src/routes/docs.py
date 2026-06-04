from fastapi import APIRouter, Depends
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse

from security.deps import get_current_user

router = APIRouter()


@router.get("/docs", include_in_schema=False, response_class=HTMLResponse)
async def swagger_ui(current_user=Depends(get_current_user)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Online Cinema API")


@router.get("/redoc", include_in_schema=False, response_class=HTMLResponse)
async def redoc(current_user=Depends(get_current_user)):
    return get_redoc_html(openapi_url="/openapi.json", title="Online Cinema API")

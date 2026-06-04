from fastapi import APIRouter
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/docs", include_in_schema=False, response_class=HTMLResponse)
async def swagger_ui():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Online Cinema API",
        oauth2_redirect_url="/docs/oauth2-redirect",
        swagger_ui_parameters={"persistAuthorization": True},
    )


@router.get("/redoc", include_in_schema=False, response_class=HTMLResponse)
async def redoc():
    return get_redoc_html(openapi_url="/openapi.json", title="Online Cinema API")

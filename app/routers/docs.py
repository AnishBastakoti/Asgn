from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.database import get_db
from app.models import User    
from core.auth_handler import verify_password

security = HTTPBasic()

async def validate_docs_access(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(get_db) 
):
    # Fetch user from DB
    user = db.query(User).filter(User.username == credentials.username).first()
    
    # Check if user exists and is an admin
    if not user or not user.is_admin:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Verify the hashed password
    if not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    return user.username

# Custom route for Swagger
@app.get("/docs", include_in_schema=False)
async def get_documentation(username: str = Depends(validate_docs_access)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{settings.APP_NAME} - Docs")

# Custom route for OpenAPI JSON
@app.get("/openapi.json", include_in_schema=False)
async def get_open_api_endpoint(username: str = Depends(validate_docs_access)):
    return get_openapi(title=app.title, version=app.version, routes=app.routes)
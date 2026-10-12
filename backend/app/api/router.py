from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.chat.router import router as chat_router
from app.modules.health.router import router as health_router
from app.modules.interactions.router import router as interactions_router
from app.modules.medications.router import router as medications_router
from app.modules.medicines.router import router as medicines_router
from app.modules.ocr.router import router as ocr_router
from app.modules.pharmacies.router import router as pharmacies_router
from app.modules.uploads.router import router as uploads_router
from app.modules.users.router import router as users_router

api_router = APIRouter()
for router in (
    health_router,
    auth_router,
    users_router,
    chat_router,
    medicines_router,
    interactions_router,
    pharmacies_router,
    medications_router,
    uploads_router,
    ocr_router,
):
    api_router.include_router(router)

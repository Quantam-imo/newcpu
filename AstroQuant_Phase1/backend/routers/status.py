from fastapi import APIRouter

router = APIRouter()

@router.get("/status")
def status():
    return {"status": "AstroQuant Phase 1 Running"}

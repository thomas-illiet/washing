"""Machine route package split by sub-domain."""

from fastapi import APIRouter

from . import crud, metrics, providers, provisioners


router = APIRouter()
router.include_router(crud.router)
router.include_router(metrics.router)
router.include_router(providers.router)
router.include_router(provisioners.router)

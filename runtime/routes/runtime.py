from fastapi import APIRouter, Depends

from runtime.controllers import runtime_controller as c
from runtime.core.security import require_runtime_token

router = APIRouter(
    prefix="/runtime", tags=["runtime"], dependencies=[Depends(require_runtime_token)]
)

router.add_api_route("/status", c.status, methods=["GET"], response_model=None)
router.add_api_route(
    "/models/{name:path}/load", c.load_model, methods=["POST"], response_model=None
)
router.add_api_route(
    "/models/{name:path}/unload", c.unload_model, methods=["POST"], response_model=None
)
router.add_api_route("/catalog/reload", c.reload_catalog, methods=["POST"], response_model=None)
router.add_api_route("/shutdown", c.shutdown, methods=["POST"], response_model=None)

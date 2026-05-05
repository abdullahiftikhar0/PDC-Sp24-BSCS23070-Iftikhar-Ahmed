from fastapi import HTTPException
from clerk_backend_api import Clerk, AuthenticateRequestOptions
import os
from dotenv import load_dotenv

load_dotenv()

def _get_clerk_client() -> Clerk:
    secret_key = os.getenv('CLERK_SECRET_KEY')
    if not secret_key:
        raise HTTPException(status_code=500, detail='CLERK_SECRET_KEY not set')
    return Clerk(bearer_auth=secret_key)

def authenticate_and_get_user_details(request):
    try:
        jwt_key = os.getenv('JWT_KEY')
        if not jwt_key:
            raise HTTPException(status_code=500, detail='JWT_KEY not set')

        clerk_sdk = _get_clerk_client()
        request_state = clerk_sdk.authenticate_request(
            request,
            AuthenticateRequestOptions(
                authorized_parties=["http://localhost:5173", "http://localhost:5174"],
                jwt_key=jwt_key
            )
        )

        if not request_state.is_signed_in:
            raise HTTPException(status_code=401, detail="Invalid token")

        user_id = request_state.payload.get("sub")

        return {"user_id": user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
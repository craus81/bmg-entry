"""
BMG Fleet API Service
FastAPI application exposing sales order lookup and graphics proof search
"""

import os
import base64
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv

from netsuite_client import NetSuiteClient
from sales_order_service import SalesOrderService
from graphics_service import DropboxGraphicsService

load_dotenv()

app = FastAPI(
    title="BMG Fleet API",
    description="API for sales order lookup, PDF generation, and graphics proof search",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dropbox configuration (supports refresh tokens for long-lived access)
DROPBOX_ACCESS_TOKEN = os.getenv('DROPBOX_ACCESS_TOKEN')
DROPBOX_REFRESH_TOKEN = os.getenv('DROPBOX_REFRESH_TOKEN')
DROPBOX_APP_KEY = os.getenv('DROPBOX_APP_KEY')
DROPBOX_APP_SECRET = os.getenv('DROPBOX_APP_SECRET')
DROPBOX_GRAPHICS_ROOT = os.getenv('DROPBOX_GRAPHICS_ROOT', '/OFFICE/Clients')


def get_netsuite_client() -> NetSuiteClient:
    required_vars = ['NETSUITE_ACCOUNT_ID', 'NETSUITE_CONSUMER_KEY', 'NETSUITE_CONSUMER_SECRET', 'NETSUITE_TOKEN_ID', 'NETSUITE_TOKEN_SECRET']
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise HTTPException(status_code=500, detail=f"Missing required environment variables: {', '.join(missing)}")
    return NetSuiteClient(
        account_id=os.getenv('NETSUITE_ACCOUNT_ID'),
        consumer_key=os.getenv('NETSUITE_CONSUMER_KEY'),
        consumer_secret=os.getenv('NETSUITE_CONSUMER_SECRET'),
        token_id=os.getenv('NETSUITE_TOKEN_ID'),
        token_secret=os.getenv('NETSUITE_TOKEN_SECRET')
    )


def get_graphics_service() -> Optional[DropboxGraphicsService]:
    # Prefer refresh token (never expires) over access token
    if DROPBOX_REFRESH_TOKEN and DROPBOX_APP_KEY and DROPBOX_APP_SECRET:
        try:
            return DropboxGraphicsService(
                root_path=DROPBOX_GRAPHICS_ROOT,
                refresh_token=DROPBOX_REFRESH_TOKEN,
                app_key=DROPBOX_APP_KEY,
                app_secret=DROPBOX_APP_SECRET
            )
        except Exception as e:
            print(f"Graphics service (refresh token) not available: {e}")
    
    # Fall back to access token
    if DROPBOX_ACCESS_TOKEN:
        try:
            return DropboxGraphicsService(DROPBOX_ACCESS_TOKEN, DROPBOX_GRAPHICS_ROOT)
        except Exception as e:
            print(f"Graphics service (access token) not available: {e}")
    
    return None


class CustomerLookupResponse(BaseModel):
    found: bool
    count: Optional[int] = None
    customers_matched: Optional[int] = None
    error: Optional[str] = None
    alert: Optional[bool] = None
    alert_message: Optional[str] = None
    data: Optional[List[dict]] = None
    grouped_by_customer: Optional[List[dict]] = None


# ===========================================
# Health & Root Endpoints
# ===========================================

@app.get("/", tags=["Health"])
async def root():
    return {"status": "healthy", "service": "BMG Fleet API", "version": "3.0.0"}


@app.get("/health", tags=["Health"])
async def health_check():
    netsuite_configured = all([os.getenv(v) for v in ['NETSUITE_ACCOUNT_ID', 'NETSUITE_CONSUMER_KEY', 'NETSUITE_CONSUMER_SECRET', 'NETSUITE_TOKEN_ID', 'NETSUITE_TOKEN_SECRET']])
    dropbox_configured = bool(DROPBOX_ACCESS_TOKEN)
    return {
        "status": "healthy" if netsuite_configured else "misconfigured",
        "netsuite_configured": netsuite_configured,
        "dropbox_configured": dropbox_configured,
        "graphics_root": DROPBOX_GRAPHICS_ROOT if dropbox_configured else None
    }


# ===========================================
# Sales Order Endpoints
# ===========================================

@app.get("/sales-orders/customer/{customer_name}", response_model=CustomerLookupResponse, tags=["Sales Orders"])
async def get_sales_orders_by_customer(customer_name: str):
    try:
        client = get_netsuite_client()
        service = SalesOrderService(client)
        return service.get_open_sales_orders_by_customer(customer_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sales-order/{sales_order_id}/pdf", tags=["PDF"])
async def get_sales_order_pdf(sales_order_id: str):
    """Get the PDF of a sales order as base64."""
    try:
        client = get_netsuite_client()
        service = SalesOrderService(client)
        return service.get_sales_order_pdf(sales_order_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================
# Graphics Endpoints (Dropbox-backed)
# ===========================================

@app.get("/graphics/customers", tags=["Graphics"])
async def list_graphics_customers():
    """List all customer folders in Dropbox"""
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail="Graphics service not available - check DROPBOX_ACCESS_TOKEN")
    
    try:
        customers = service.list_customers()
        return {"count": len(customers), "customers": customers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graphics/customer/{customer_name}/folders", tags=["Graphics"], summary="List vehicle folders for a customer")
async def list_customer_folders(customer_name: str):
    """List all vehicle type folders for a customer"""
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail="Graphics service not available")
    
    try:
        result = service.list_customer_folders(customer_name)
        if not result['found']:
            raise HTTPException(status_code=404, detail=result.get('error', 'Customer not found'))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graphics/customer/{customer_name}/folder/{folder_name}/proofs", tags=["Graphics"], summary="Get proofs from a specific folder")
async def get_folder_proofs(
    customer_name: str,
    folder_name: str,
    thumbnails: bool = Query(True, description="Include thumbnail images")
):
    """Get all proofs from a specific vehicle folder"""
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail="Graphics service not available")
    
    try:
        result = service.get_folder_proofs(customer_name, folder_name, include_thumbnails=thumbnails)
        
        # Add download URLs
        if result.get('proofs'):
            for proof in result['proofs']:
                proof['download_url'] = f"/graphics/download?path={proof['file_path']}"
        
        if not result['found']:
            raise HTTPException(status_code=404, detail=result.get('error', 'Folder not found'))
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graphics/proofs/all", tags=["Graphics"], summary="Find all matching proofs")
async def find_all_graphics_proofs(
    customer: str = Query(..., description="Customer name"),
    vehicle_type: str = Query(..., description="Vehicle type"),
    thumbnails: bool = Query(True, description="Include thumbnail images")
):
    """Find all matching proofs for a customer/vehicle type"""
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail="Graphics service not available")
    
    try:
        result = service.find_all_proofs(customer, vehicle_type, include_thumbnails=thumbnails)
        
        # Add download URLs
        if result.get('proofs'):
            for proof in result['proofs']:
                proof['download_url'] = f"/graphics/download?path={proof['file_path']}"
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graphics/download", tags=["Graphics"], summary="Get download link for a proof")
async def get_proof_download_link(path: str = Query(..., description="Dropbox path to the file")):
    """Get a temporary download link for a proof file"""
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail="Graphics service not available")
    
    try:
        result = service.get_proof_download_url(path)
        if not result['success']:
            raise HTTPException(status_code=404, detail=result.get('error', 'File not found'))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graphics/vehicle-types/{customer_name}", tags=["Graphics"])
async def list_vehicle_types(customer_name: str):
    """List vehicle type folders for a customer"""
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail="Graphics service not available")
    
    try:
        result = service.list_customer_folders(customer_name)
        if not result['found']:
            raise HTTPException(status_code=404, detail=result.get('error', 'Customer not found'))
        
        vehicle_types = [f['name'] for f in result.get('folders', [])]
        return {"customer": customer_name, "count": len(vehicle_types), "vehicle_types": vehicle_types}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================
# Monday.com Integration Endpoints
# ===========================================

@app.post("/monday/upload-file", tags=["Monday"])
async def upload_file_to_monday(
    item_id: str = Query(..., description="Monday.com item ID"),
    column_id: str = Query(..., description="Monday.com column ID"),
    file_path: str = Query(..., description="Dropbox path to the file"),
    api_token: str = Query(..., description="Monday.com API token")
):
    """Download from Dropbox and upload to Monday.com"""
    import requests as req
    
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail="Graphics service not available")
    
    try:
        # Download from Dropbox
        download_result = service.download_proof(file_path)
        if not download_result['success']:
            raise HTTPException(status_code=404, detail=download_result.get('error', 'File not found'))
        
        file_content = base64.b64decode(download_result['content'])
        filename = download_result['filename']
        
        # Upload to Monday.com
        url = "https://api.monday.com/v2/file"
        query = f'mutation ($file: File!) {{ add_file_to_column (item_id: {item_id}, column_id: "{column_id}", file: $file) {{ id }} }}'
        
        files = {
            'query': (None, query),
            'variables[file]': (filename, file_content, 'application/pdf')
        }
        
        headers = {'Authorization': api_token}
        response = req.post(url, files=files, headers=headers)
        result = response.json()
        
        if 'errors' in result:
            raise HTTPException(status_code=400, detail=result['errors'][0]['message'])
        
        return {"success": True, "result": result}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/monday/upload-sales-order-pdf", tags=["Monday"])
async def upload_sales_order_pdf_to_monday(
    item_id: str = Query(..., description="Monday.com item ID"),
    column_id: str = Query(..., description="Monday.com column ID"),
    sales_order_id: str = Query(..., description="NetSuite Sales Order ID"),
    api_token: str = Query(..., description="Monday.com API token")
):
    """Get sales order PDF from NetSuite and upload to Monday.com."""
    import requests as req
    
    try:
        client = get_netsuite_client()
        service = SalesOrderService(client)
        pdf_result = service.get_sales_order_pdf(sales_order_id)
        
        if not pdf_result.get('success'):
            raise HTTPException(status_code=400, detail=pdf_result.get('error', 'Failed to get PDF'))
        
        pdf_content = base64.b64decode(pdf_result['pdf_base64'])
        filename = pdf_result.get('filename', f'SalesOrder_{sales_order_id}.pdf')
        
        url = "https://api.monday.com/v2/file"
        query = f'mutation ($file: File!) {{ add_file_to_column (item_id: {item_id}, column_id: "{column_id}", file: $file) {{ id }} }}'
        
        files = {
            'query': (None, query),
            'variables[file]': (filename, pdf_content, 'application/pdf')
        }
        
        headers = {'Authorization': api_token}
        response = req.post(url, files=files, headers=headers)
        result = response.json()
        
        if 'errors' in result:
            raise HTTPException(status_code=400, detail=result['errors'][0]['message'])
        
        return {"success": True, "result": result}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================
# Widget & PWA Endpoints
# ===========================================

@app.get("/widget", tags=["Widget"])
async def serve_widget():
    """Serve the vehicle check-in widget."""
    return FileResponse("/app/BMG-Fleet-Vehicle-Check-In.html")


@app.get("/config/monday-token", tags=["Config"])
async def get_monday_token():
    """Get Monday.com API token from server config."""
    token = os.getenv('MONDAY_API_TOKEN')
    if not token:
        raise HTTPException(status_code=404, detail="Monday token not configured")
    return {"token": token}


@app.get("/manifest.json", tags=["PWA"])
async def serve_manifest():
    """Serve PWA manifest."""
    return FileResponse("/app/manifest.json", media_type="application/manifest+json")


@app.get("/sw.js", tags=["PWA"])
async def serve_service_worker():
    """Serve service worker."""
    return FileResponse("/app/sw.js", media_type="application/javascript")


@app.get("/icon-192.png", tags=["PWA"])
async def serve_icon_192():
    """Serve 192x192 icon."""
    return FileResponse("/app/icon-192.png", media_type="image/png")


@app.get("/icon-512.png", tags=["PWA"])
async def serve_icon_512():
    """Serve 512x512 icon."""
    return FileResponse("/app/icon-512.png", media_type="image/png")


@app.get("/bmg-logo-white.png", tags=["Assets"])
async def serve_logo_white():
    """Serve white logo for dark mode."""
    return FileResponse("/app/bmg-logo-white.png", media_type="image/png")


@app.get("/bmg-logo-color.png", tags=["Assets"])
async def serve_logo_color():
    """Serve color logo for light mode."""
    return FileResponse("/app/bmg-logo-color.png", media_type="image/png")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""
BMG Fleet API Service
FastAPI application exposing sales order lookup and graphics proof search
"""

import os
import base64
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv

from netsuite_client import NetSuiteClient
from sales_order_service import SalesOrderService
from graphics_service import GraphicsProofService, ProofResult

load_dotenv()

app = FastAPI(
    title="BMG Fleet API",
    description="API for sales order lookup, PDF generation, and graphics proof search",
    version="2.3.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GRAPHICS_ROOT = os.getenv('GRAPHICS_ROOT', '/volume1/graphics/Clients')


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


def get_graphics_service() -> Optional[GraphicsProofService]:
    try:
        if os.path.exists(GRAPHICS_ROOT):
            return GraphicsProofService(GRAPHICS_ROOT)
    except Exception as e:
        print(f"Graphics service not available: {e}")
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


@app.get("/", tags=["Health"])
async def root():
    return {"status": "healthy", "service": "BMG Fleet API", "version": "2.3.0"}


@app.get("/health", tags=["Health"])
async def health_check():
    netsuite_configured = all([os.getenv(v) for v in ['NETSUITE_ACCOUNT_ID', 'NETSUITE_CONSUMER_KEY', 'NETSUITE_CONSUMER_SECRET', 'NETSUITE_TOKEN_ID', 'NETSUITE_TOKEN_SECRET']])
    return {
        "status": "healthy" if netsuite_configured else "misconfigured",
        "netsuite_configured": netsuite_configured,
        "graphics_available": os.path.exists(GRAPHICS_ROOT),
        "graphics_root": GRAPHICS_ROOT
    }


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


# ===========================================
# Graphics Endpoints
# ===========================================

@app.get("/graphics/customer/{customer_name}/folders", tags=["Graphics"], summary="List vehicle folders for a customer")
async def list_customer_folders(customer_name: str):
    """
    List all vehicle type folders for a customer (fast, no thumbnails).
    Returns folder names with proof counts.
    """
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
    """
    Get all proofs from a specific vehicle folder with thumbnails.
    """
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail="Graphics service not available")
    
    try:
        result = service.get_folder_proofs(customer_name, folder_name, include_thumbnails=thumbnails)
        
        if result.get('proofs'):
            for proof in result['proofs']:
                proof['download_url'] = f"/graphics/file/download?path={proof['relative_path']}"
        
        if not result['found']:
            raise HTTPException(status_code=404, detail=result.get('error', 'Folder not found'))
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graphics/proofs/all", tags=["Graphics"], summary="Find all matching proofs with thumbnails")
async def find_all_graphics_proofs(
    customer: str = Query(..., description="Customer name"),
    vehicle_type: str = Query(..., description="Vehicle type"),
    thumbnails: bool = Query(True, description="Include thumbnail images")
):
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail=f"Graphics service not available. Check GRAPHICS_ROOT: {GRAPHICS_ROOT}")
    
    try:
        result = service.find_all_proofs(customer, vehicle_type, include_thumbnails=thumbnails)
        if result.get('proofs'):
            for proof in result['proofs']:
                proof['download_url'] = f"/graphics/file/download?path={proof['relative_path']}"
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graphics/file/download", tags=["Graphics"], summary="Download a specific proof file by path")
async def download_graphics_file(path: str = Query(..., description="Relative path to the file")):
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail="Graphics service not available")
    
    try:
        full_path = service.graphics_root / path
        if not str(full_path.resolve()).startswith(str(service.graphics_root.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(path=str(full_path), filename=full_path.name, media_type='application/octet-stream')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graphics/customers", tags=["Graphics"])
async def list_graphics_customers():
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail="Graphics service not available")
    customers = service.list_customers()
    return {"count": len(customers), "customers": customers}


@app.get("/graphics/vehicle-types/{customer_name}", tags=["Graphics"])
async def list_vehicle_types(customer_name: str):
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail="Graphics service not available")
    vehicle_types = service.list_vehicle_types(customer_name)
    return {"customer": customer_name, "count": len(vehicle_types), "vehicle_types": vehicle_types}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


@app.post("/monday/upload-file", tags=["Monday"])
async def upload_file_to_monday(
    item_id: str = Query(..., description="Monday.com item ID"),
    column_id: str = Query(..., description="Monday.com column ID"),
    file_path: str = Query(..., description="Relative path to the file"),
    api_token: str = Query(..., description="Monday.com API token")
):
    """Upload a file to Monday.com via proxy to avoid CORS issues."""
    import requests
    
    service = get_graphics_service()
    if not service:
        raise HTTPException(status_code=503, detail="Graphics service not available")
    
    full_path = service.graphics_root / file_path
    
    # Security check
    if not str(full_path.resolve()).startswith(str(service.graphics_root.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        # Read the file
        with open(full_path, 'rb') as f:
            file_content = f.read()
        
        # Upload to Monday.com
        url = "https://api.monday.com/v2/file"
        
        query = f'mutation ($file: File!) {{ add_file_to_column (item_id: {item_id}, column_id: "{column_id}", file: $file) {{ id }} }}'
        
        files = {
            'query': (None, query),
            'variables[file]': (full_path.name, file_content, 'application/pdf')
        }
        
        headers = {
            'Authorization': api_token
        }
        
        response = requests.post(url, files=files, headers=headers)
        result = response.json()
        
        if 'errors' in result:
            raise HTTPException(status_code=400, detail=result['errors'][0]['message'])
        
        return {"success": True, "result": result}
    
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


@app.post("/monday/upload-sales-order-pdf", tags=["Monday"])
async def upload_sales_order_pdf_to_monday(
    item_id: str = Query(..., description="Monday.com item ID"),
    column_id: str = Query(..., description="Monday.com column ID"),
    sales_order_id: str = Query(..., description="NetSuite Sales Order ID"),
    api_token: str = Query(..., description="Monday.com API token")
):
    """Get sales order PDF from NetSuite and upload to Monday.com."""
    import requests
    import base64
    
    try:
        client = get_netsuite_client()
        service = SalesOrderService(client)
        pdf_result = service.get_sales_order_pdf(sales_order_id)
        
        if not pdf_result.get('success'):
            raise HTTPException(status_code=400, detail=pdf_result.get('error', 'Failed to get PDF'))
        
        # Decode base64 PDF
        pdf_content = base64.b64decode(pdf_result['pdf_base64'])
        filename = pdf_result.get('filename', f'SalesOrder_{sales_order_id}.pdf')
        
        # Upload to Monday.com
        url = "https://api.monday.com/v2/file"
        
        query = f'mutation ($file: File!) {{ add_file_to_column (item_id: {item_id}, column_id: "{column_id}", file: $file) {{ id }} }}'
        
        files = {
            'query': (None, query),
            'variables[file]': (filename, pdf_content, 'application/pdf')
        }
        
        headers = {
            'Authorization': api_token
        }
        
        response = requests.post(url, files=files, headers=headers)
        result = response.json()
        
        if 'errors' in result:
            raise HTTPException(status_code=400, detail=result['errors'][0]['message'])
        
        return {"success": True, "result": result}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

@app.get("/widget", tags=["Widget"])
async def serve_widget():
    """Serve the vehicle check-in widget."""
    return FileResponse("/app/BMG-Fleet-Vehicle-Check-In.html")


@app.get("/config/monday-token", tags=["Config"])
async def get_monday_token():
    """Get Monday.com API token from server config."""
    import os
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

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os

app = FastAPI(title="BMG Fleet Vehicle Entry")

# Serve the main HTML file
@app.get("/")
async def root():
    return FileResponse("BMG-Fleet-Vehicle-Check-In.html")

# Serve static files (icons, etc.)
@app.get("/{filename}")
async def serve_file(filename: str):
    if os.path.exists(filename):
        return FileResponse(filename)
    return {"error": "File not found"}

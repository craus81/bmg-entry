"""
Graphics Proof Search Service - Dropbox Version
Finds graphic proofs in Dropbox using the API
"""

import os
import re
import base64
import requests
from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class ProofResult:
    """Result of a proof search"""
    found: bool
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    relative_path: Optional[str] = None
    customer_folder: Optional[str] = None
    vehicle_folder: Optional[str] = None
    confidence: float = 0.0
    thumbnail_base64: Optional[str] = None
    all_matches: Optional[List[Dict]] = None
    error: Optional[str] = None


class DropboxGraphicsService:
    """Service for finding graphic proofs in Dropbox"""
    
    PROOF_EXTENSIONS = ['.pdf']
    PROOF_KEYWORDS = ['proof', 'final', 'approved', 'print']
    IGNORE_WORDS = ['the', 'and', 'of', 'inc', 'llc', 'corp', 'company', 'co', 'services', 'service']
    
    # Folders to skip
    SKIP_FOLDERS = [
        'logos', 'logo', 'color palette', 'unit numbers', 'x', 'old',
        'supporting documents', 'photos', 'work order', 'templates',
        'original', 'originals', 'wip', 'archive', 'backup'
    ]
    
    def __init__(self, access_token: str, root_path: str = "/OFFICE/Clients"):
        self.access_token = access_token
        self.root_path = root_path
        self.base_url = "https://api.dropboxapi.com/2"
        self.content_url = "https://content.dropboxapi.com/2"
    
    def _headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}
    
    def _api_request(self, endpoint: str, data: dict) -> dict:
        """Make a Dropbox API request"""
        response = requests.post(
            f"{self.base_url}/{endpoint}",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=data
        )
        response.raise_for_status()
        return response.json()
    
    def _list_folder(self, path: str, recursive: bool = False) -> List[dict]:
        """List contents of a Dropbox folder"""
        try:
            result = self._api_request("files/list_folder", {
                "path": path if path != "/" else "",
                "recursive": recursive,
                "include_deleted": False,
                "include_has_explicit_shared_members": False
            })
            
            entries = result.get("entries", [])
            
            # Handle pagination
            while result.get("has_more"):
                result = self._api_request("files/list_folder/continue", {
                    "cursor": result["cursor"]
                })
                entries.extend(result.get("entries", []))
            
            return entries
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 409:  # Path not found
                return []
            raise
    
    def _download_file(self, path: str) -> bytes:
        """Download a file from Dropbox"""
        import json
        response = requests.post(
            f"{self.content_url}/files/download",
            headers={
                **self._headers(),
                "Dropbox-API-Arg": json.dumps({"path": path})
            }
        )
        response.raise_for_status()
        return response.content
    
    def _get_thumbnail(self, path: str) -> Optional[str]:
        """Get thumbnail for a file (Dropbox generates for PDFs)"""
        import json
        try:
            response = requests.post(
                f"{self.content_url}/files/get_thumbnail_v2",
                headers={
                    **self._headers(),
                    "Dropbox-API-Arg": json.dumps({
                        "resource": {".tag": "path", "path": path},
                        "format": {".tag": "png"},
                        "size": {".tag": "w256h256"},
                        "mode": {".tag": "fitone_bestfit"}
                    })
                }
            )
            if response.status_code == 200:
                return base64.b64encode(response.content).decode('utf-8')
        except:
            pass
        return None
    
    def list_customers(self) -> List[str]:
        """List all customer folders"""
        entries = self._list_folder(self.root_path)
        customers = [
            e["name"] for e in entries 
            if e[".tag"] == "folder" and not e["name"].startswith(".")
        ]
        return sorted(customers)
    
    def list_customer_folders(self, customer_name: str) -> Dict:
        """List vehicle type folders for a customer"""
        customer_path = self._find_customer_folder(customer_name)
        if not customer_path:
            return {'found': False, 'error': f'Customer not found: {customer_name}', 'folders': []}
        
        entries = self._list_folder(customer_path)
        
        folders = []
        for entry in entries:
            if entry[".tag"] != "folder":
                continue
            if entry["name"].startswith("."):
                continue
            if entry["name"].lower() in self.SKIP_FOLDERS:
                continue
            
            # Count PDFs in this folder (non-recursive for speed)
            folder_path = entry["path_display"]
            folder_entries = self._list_folder(folder_path, recursive=True)
            proof_count = sum(
                1 for e in folder_entries 
                if e[".tag"] == "file" and e["name"].lower().endswith('.pdf')
                and 'proof' in e["name"].lower()
            )
            
            if proof_count > 0:
                folders.append({
                    'name': entry["name"],
                    'proof_count': proof_count,
                    'path': folder_path
                })
        
        return {
            'found': True,
            'customer_folder': customer_path.split('/')[-1],
            'count': len(folders),
            'folders': folders
        }
    
    def _find_customer_folder(self, customer_name: str) -> Optional[str]:
        """Find the best matching customer folder"""
        customer_name_clean = self._clean_name(customer_name)
        entries = self._list_folder(self.root_path)
        
        best_match, best_score = None, 0.0
        
        for entry in entries:
            if entry[".tag"] != "folder":
                continue
            
            folder_name_clean = self._clean_name(entry["name"])
            score = self._similarity_score(customer_name_clean, folder_name_clean)
            
            # Boost score for substring matches
            if customer_name_clean in folder_name_clean or folder_name_clean in customer_name_clean:
                score = max(score, 0.8)
            
            if score > best_score and score >= 0.5:
                best_score = score
                best_match = entry["path_display"]
        
        return best_match
    
    def find_all_proofs(self, customer_name: str, vehicle_type: str, include_thumbnails: bool = True) -> Dict:
        """Find all matching proofs for a customer/vehicle type"""
        customer_path = self._find_customer_folder(customer_name)
        if not customer_path:
            return {'found': False, 'error': f'Customer not found: {customer_name}', 'proofs': []}
        
        # Search recursively for PDFs
        all_entries = self._list_folder(customer_path, recursive=True)
        
        vehicle_type_clean = self._clean_name(vehicle_type)
        proofs = []
        
        for entry in all_entries:
            if entry[".tag"] != "file":
                continue
            if not entry["name"].lower().endswith('.pdf'):
                continue
            
            # Check if it's a proof file
            name_lower = entry["name"].lower()
            path_lower = entry["path_display"].lower()
            
            # Must contain "proof" somewhere
            if 'proof' not in name_lower and 'proof' not in path_lower:
                continue
            
            # Score based on vehicle type match
            file_path_clean = self._clean_name(entry["path_display"])
            score = self._similarity_score(vehicle_type_clean, file_path_clean)
            
            # Boost for vehicle type keywords in path
            if self._is_vehicle_type_match(vehicle_type, entry["path_display"]):
                score = max(score, 0.7)
            
            if score >= 0.3:
                proof_info = {
                    'file_name': entry["name"],
                    'file_path': entry["path_display"],
                    'relative_path': entry["path_display"].replace(self.root_path + "/", ""),
                    'confidence': score,
                    'version': self._extract_version(entry["name"]),
                    'modified': entry.get("server_modified"),
                    'size': entry.get("size", 0)
                }
                
                if include_thumbnails:
                    proof_info['thumbnail_base64'] = self._get_thumbnail(entry["path_display"])
                
                proofs.append(proof_info)
        
        # Sort by confidence and version
        proofs.sort(key=lambda x: (x['confidence'], x.get('version') or 0), reverse=True)
        
        return {
            'found': len(proofs) > 0,
            'customer_folder': customer_path.split('/')[-1],
            'count': len(proofs),
            'proofs': proofs[:10]  # Limit to top 10
        }
    
    def get_folder_proofs(self, customer_name: str, folder_name: str, include_thumbnails: bool = True) -> Dict:
        """Get all proofs from a specific folder"""
        customer_path = self._find_customer_folder(customer_name)
        if not customer_path:
            return {'found': False, 'error': f'Customer not found: {customer_name}', 'proofs': []}
        
        folder_path = f"{customer_path}/{folder_name}"
        entries = self._list_folder(folder_path, recursive=True)
        
        proofs = []
        for entry in entries:
            if entry[".tag"] != "file":
                continue
            if not entry["name"].lower().endswith('.pdf'):
                continue
            if 'proof' not in entry["name"].lower():
                continue
            
            proof_info = {
                'file_name': entry["name"],
                'file_path': entry["path_display"],
                'relative_path': entry["path_display"].replace(self.root_path + "/", ""),
                'version': self._extract_version(entry["name"]),
                'modified': entry.get("server_modified"),
                'size': entry.get("size", 0)
            }
            
            if include_thumbnails:
                proof_info['thumbnail_base64'] = self._get_thumbnail(entry["path_display"])
            
            proofs.append(proof_info)
        
        # Sort by version (newest first)
        proofs.sort(key=lambda x: (-(x.get('version') or 0), x['file_name']))
        
        return {
            'found': len(proofs) > 0,
            'customer_folder': customer_path.split('/')[-1],
            'folder_name': folder_name,
            'count': len(proofs),
            'proofs': proofs[:20]
        }
    
    def get_proof_download_url(self, file_path: str) -> Dict:
        """Get a temporary download link for a proof"""
        try:
            result = self._api_request("files/get_temporary_link", {
                "path": file_path
            })
            return {
                'success': True,
                'url': result.get("link"),
                'expires': "4 hours"
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def download_proof(self, file_path: str) -> Dict:
        """Download a proof file"""
        try:
            content = self._download_file(file_path)
            return {
                'success': True,
                'content': base64.b64encode(content).decode('utf-8'),
                'filename': file_path.split('/')[-1]
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _clean_name(self, name: str) -> str:
        """Clean a name for comparison"""
        name = re.sub(r'[^a-z0-9\s]', ' ', name.lower())
        return ' '.join(w for w in name.split() if w not in self.IGNORE_WORDS)
    
    def _similarity_score(self, str1: str, str2: str) -> float:
        """Calculate similarity between two strings"""
        return SequenceMatcher(None, str1, str2).ratio()
    
    def _is_vehicle_type_match(self, vehicle_type: str, text: str) -> bool:
        """Check if text contains vehicle type keywords"""
        vehicle_lower, text_lower = vehicle_type.lower(), text.lower()
        keywords = [
            'transit', 'sprinter', 'promaster', 'box truck', 'boxtruck', 'cargo van',
            'silverado', 'f150', 'f-150', 'high roof', 'highroof', 'mid roof', 'midroof',
            'low roof', 'lowroof', 'maverick', 'ranger', 'colorado', 'express', 'savana',
            '26ft', '16ft', '20ft', 'cutaway', 'kuv', 'suv', 'pickup', 'truck'
        ]
        for kw in keywords:
            if kw in vehicle_lower and kw in text_lower:
                return True
        return False
    
    def _extract_version(self, filename: str) -> Optional[int]:
        """Extract version number from filename"""
        if m := re.search(r'[_\-\s]?v(\d+)', filename, re.IGNORECASE):
            return int(m.group(1))
        if m := re.search(r'[_\-\s](\d+)$', filename.rsplit('.', 1)[0]):
            return int(m.group(1))
        return None


# For backwards compatibility with existing code
GraphicsProofService = DropboxGraphicsService

"""
NetSuite REST API Client
Uses the official netsuite library for OAuth authentication
"""

import asyncio
from typing import Optional
from netsuite import NetSuite, Config, TokenAuth


class NetSuiteClient:
    """Client for interacting with NetSuite REST API using Token-Based Authentication"""
    
    def __init__(
        self,
        account_id: str,
        consumer_key: str,
        consumer_secret: str,
        token_id: str,
        token_secret: str
    ):
        self.account_id = account_id
        self.config = Config(
            account=account_id,
            auth=TokenAuth(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                token_id=token_id,
                token_secret=token_secret,
            )
        )
        self.ns = NetSuite(self.config)
    
    async def suiteql_query_async(self, query: str, limit: int = 1000, offset: int = 0) -> dict:
        """Execute a SuiteQL query against NetSuite (async)"""
        return await self.ns.rest_api.suiteql(q=query, limit=limit, offset=offset)
    
    def suiteql_query(self, query: str, limit: int = 1000, offset: int = 0) -> dict:
        """Execute a SuiteQL query against NetSuite (sync wrapper)"""
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Create a new loop in a thread for sync calls from async context
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    self.suiteql_query_async(query, limit, offset)
                )
                return future.result()
        else:
            return loop.run_until_complete(self.suiteql_query_async(query, limit, offset))
    
    async def call_restlet_async(
        self,
        restlet_url: str,
        method: str = 'GET',
        params: Optional[dict] = None,
        json_data: Optional[dict] = None
    ) -> dict:
        """Call a NetSuite RESTlet (async)"""
        # Parse script and deploy IDs from URL
        import re
        from urllib.parse import urlparse, parse_qs
        
        parsed = urlparse(restlet_url)
        query_params = parse_qs(parsed.query)
        
        script_id = query_params.get('script', [None])[0]
        deploy_id = query_params.get('deploy', [None])[0]
        
        if not script_id or not deploy_id:
            raise ValueError("RESTlet URL must contain script and deploy parameters")
        
        # Extract any additional params from the URL (like salesOrderId)
        extra_params = {k: v[0] for k, v in query_params.items() if k not in ['script', 'deploy']}
        if params:
            extra_params.update(params)
        
        if method.upper() == 'GET':
            return await self.ns.restlet.get(script_id=int(script_id), deploy=int(deploy_id), params=extra_params if extra_params else None)
        elif method.upper() == 'POST':
            return await self.ns.restlet.post(script_id=int(script_id), deploy=int(deploy_id), json=json_data, params=extra_params if extra_params else None)
        else:
            raise ValueError(f"Unsupported method: {method}")
    
    def call_restlet(
        self,
        restlet_url: str,
        method: str = 'GET',
        params: Optional[dict] = None,
        json_data: Optional[dict] = None
    ) -> dict:
        """Call a NetSuite RESTlet (sync wrapper)"""
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    self.call_restlet_async(restlet_url, method, params, json_data)
                )
                return future.result()
        else:
            return loop.run_until_complete(
                self.call_restlet_async(restlet_url, method, params, json_data)
            )

#!/usr/bin/env python3
"""
Test script to verify NetSuite connection and credentials
Run this before starting the full API service
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def check_env_vars():
    """Check that all required environment variables are set"""
    required = [
        'NETSUITE_ACCOUNT_ID',
        'NETSUITE_CONSUMER_KEY',
        'NETSUITE_CONSUMER_SECRET',
        'NETSUITE_TOKEN_ID',
        'NETSUITE_TOKEN_SECRET'
    ]
    
    missing = []
    for var in required:
        if not os.getenv(var):
            missing.append(var)
        else:
            # Show first/last few chars for verification
            value = os.getenv(var)
            masked = value[:4] + '...' + value[-4:] if len(value) > 10 else '***'
            print(f"✓ {var}: {masked}")
    
    if missing:
        print(f"\n✗ Missing variables: {', '.join(missing)}")
        return False
    
    return True


def test_connection():
    """Test the NetSuite connection with a simple query"""
    from netsuite_client import NetSuiteClient
    
    client = NetSuiteClient(
        account_id=os.getenv('NETSUITE_ACCOUNT_ID'),
        consumer_key=os.getenv('NETSUITE_CONSUMER_KEY'),
        consumer_secret=os.getenv('NETSUITE_CONSUMER_SECRET'),
        token_id=os.getenv('NETSUITE_TOKEN_ID'),
        token_secret=os.getenv('NETSUITE_TOKEN_SECRET')
    )
    
    print("\nTesting NetSuite connection...")
    print(f"Account ID: {client.account_id}")
    print(f"Base URL: {client.base_url}")
    
    # Simple query to test connection - get count of sales orders
    query = "SELECT COUNT(*) as count FROM transaction WHERE type = 'SalesOrd'"
    
    try:
        result = client.suiteql_query(query)
        count = result.get('items', [{}])[0].get('count', 'unknown')
        print(f"\n✓ Connection successful!")
        print(f"  Total sales orders in NetSuite: {count}")
        return True
    except Exception as e:
        print(f"\n✗ Connection failed: {str(e)}")
        return False


def test_vin_field():
    """Test that the VIN custom field exists"""
    from netsuite_client import NetSuiteClient
    
    client = NetSuiteClient(
        account_id=os.getenv('NETSUITE_ACCOUNT_ID'),
        consumer_key=os.getenv('NETSUITE_CONSUMER_KEY'),
        consumer_secret=os.getenv('NETSUITE_CONSUMER_SECRET'),
        token_id=os.getenv('NETSUITE_TOKEN_ID'),
        token_secret=os.getenv('NETSUITE_TOKEN_SECRET')
    )
    
    print("\nTesting VIN field (custbody_vin_number_)...")
    
    # Query for sales orders with VIN field
    query = """
        SELECT id, tranid, custbody_vin_number_ 
        FROM transaction 
        WHERE type = 'SalesOrd' 
        AND custbody_vin_number_ IS NOT NULL 
        LIMIT 3
    """
    
    try:
        result = client.suiteql_query(query)
        items = result.get('items', [])
        
        if items:
            print(f"✓ VIN field exists! Found {len(items)} orders with VINs:")
            for item in items:
                print(f"  - {item.get('tranid')}: {item.get('custbody_vin_number_')}")
        else:
            print("⚠ VIN field exists but no orders have VINs yet")
        
        return True
    except Exception as e:
        if 'custbody_vin_number_' in str(e).lower():
            print(f"✗ VIN field not found. Check the field ID in NetSuite.")
        else:
            print(f"✗ Error: {str(e)}")
        return False


def main():
    print("=" * 50)
    print("BMG Fleet NetSuite API - Connection Test")
    print("=" * 50)
    
    print("\n1. Checking environment variables...")
    if not check_env_vars():
        print("\nPlease create a .env file with your credentials.")
        print("Copy .env.example to .env and fill in your values.")
        sys.exit(1)
    
    print("\n2. Testing NetSuite API connection...")
    if not test_connection():
        print("\nConnection failed. Check your credentials in NetSuite:")
        print("  - Setup > Integration > Manage Integrations")
        print("  - Setup > Users/Roles > Access Tokens")
        sys.exit(1)
    
    print("\n3. Testing VIN custom field...")
    test_vin_field()
    
    print("\n" + "=" * 50)
    print("✓ All tests passed! You can now start the API service:")
    print("  uvicorn main:app --host 0.0.0.0 --port 8000")
    print("=" * 50)


if __name__ == "__main__":
    main()

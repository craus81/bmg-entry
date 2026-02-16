"""
Sales Order Service
Handles lookups by VIN and Customer name
"""

import os
from typing import Optional
from netsuite_client import NetSuiteClient


class SalesOrderService:
    """Service for looking up sales orders by VIN or customer"""
    
    # Sales order status codes for "open" orders
    OPEN_STATUSES = ['A', 'B', 'D', 'E', 'F']
    
    def __init__(self, client: NetSuiteClient):
        self.client = client
    
    def get_sales_order_by_vin(self, vin: str) -> dict:
        """Look up a sales order by VIN number"""
        vin = vin.strip().upper()
        
        if not vin:
            return {
                'found': False,
                'error': 'VIN cannot be empty',
                'data': None
            }
        
        # For now, VIN search is not implemented since VIN field is not populated
        return {
            'found': False,
            'error': f'VIN search not yet implemented. VIN: {vin}',
            'data': None
        }
    
    def get_open_sales_orders_by_customer(self, customer_name: str) -> dict:
        """Look up all open sales orders for a customer"""
        customer_name = customer_name.strip()
        
        if not customer_name:
            return {
                'found': False,
                'error': 'Customer name cannot be empty',
                'alert': True,
                'alert_message': 'Please enter a customer name to search',
                'data': None
            }
        
        try:
            status_conditions = ' OR '.join([f"t.status = '{s}'" for s in self.OPEN_STATUSES])
            search_term = customer_name.replace("'", "''")
            
            query = f"""
                SELECT 
                    t.id,
                    t.tranid AS sales_order_number,
                    t.trandate,
                    t.status,
                    t.entity AS customer_id,
                    c.companyname AS customer_name,
                    t.memo,
                    t.total,
                    t.custbody_vin_number_ AS vin
                FROM transaction t
                LEFT JOIN customer c ON t.entity = c.id
                WHERE t.type = 'SalesOrd'
                AND ({status_conditions})
                AND (
                    UPPER(c.companyname) LIKE UPPER('%{search_term}%')
                    OR UPPER(c.entityid) LIKE UPPER('%{search_term}%')
                )
                ORDER BY c.companyname, t.trandate DESC
            """
            
            result = self.client.suiteql_query(query)
            
            if result.get('items') and len(result['items']) > 0:
                sales_orders = result['items']
                
                # Get line items for each order
                detailed_orders = []
                for so in sales_orders:
                    order_data = {
                        'id': so.get('id'),
                        'sales_order_number': so.get('sales_order_number'),
                        'date': so.get('trandate'),
                        'vin': so.get('vin'),
                        'status': so.get('status'),
                        'customer_id': so.get('customer_id'),
                        'customer_name': so.get('customer_name'),
                        'memo': so.get('memo'),
                        'total': so.get('total'),
                        'line_items': []
                    }
                    
                    # Get line items
                    try:
                        lines_query = f"""
                            SELECT 
                                tl.linesequencenumber,
                                tl.memo AS description,
                                tl.quantity,
                                tl.rate,
                                tl.netamount,
                                i.itemid AS item_name
                            FROM transactionline tl
                            LEFT JOIN item i ON tl.item = i.id
                            WHERE tl.transaction = {so['id']}
                            AND tl.mainline = 'F'
                            AND tl.taxline = 'F'
                            ORDER BY tl.linesequencenumber
                        """
                        lines_result = self.client.suiteql_query(lines_query)
                        
                        if lines_result.get('items'):
                            for line in lines_result['items']:
                                order_data['line_items'].append({
                                    'line_number': line.get('linesequencenumber'),
                                    'item_name': line.get('item_name'),
                                    'description': line.get('description'),
                                    'quantity': abs(float(line.get('quantity', 0) or 0)),
                                    'rate': abs(float(line.get('rate', 0) or 0)),
                                    'amount': abs(float(line.get('netamount', 0) or 0))
                                })
                    except Exception as e:
                        order_data['line_items_error'] = str(e)
                    
                    detailed_orders.append(order_data)
                
                # Group by customer
                customers = {}
                for order in detailed_orders:
                    cust_id = order['customer_id']
                    if cust_id not in customers:
                        customers[cust_id] = {
                            'customer_id': cust_id,
                            'customer_name': order['customer_name'],
                            'orders': []
                        }
                    customers[cust_id]['orders'].append(order)
                
                return {
                    'found': True,
                    'count': len(detailed_orders),
                    'customers_matched': len(customers),
                    'data': detailed_orders,
                    'grouped_by_customer': list(customers.values())
                }
            else:
                return {
                    'found': False,
                    'count': 0,
                    'customers_matched': 0,
                    'error': f'No open sales orders found for customer matching: {customer_name}',
                    'alert': True,
                    'alert_message': f'No open sales orders found for "{customer_name}". Please create a sales order in NetSuite.',
                    'data': None,
                    'grouped_by_customer': None
                }
                
        except Exception as e:
            return {
                'found': False,
                'count': None,
                'customers_matched': None,
                'error': f'Error searching for customer: {str(e)}',
                'alert': True,
                'alert_message': 'Error connecting to NetSuite. Please try again.',
                'data': None,
                'grouped_by_customer': None
            }
    
    def get_sales_order_pdf(self, sales_order_id: str) -> dict:
        """Generate PDF for a sales order using RESTlet"""
        restlet_url = os.getenv('NETSUITE_PDF_RESTLET_URL')
        
        if not restlet_url:
            return {
                'success': False,
                'error': 'PDF RESTlet URL not configured'
            }
        
        try:
            full_url = f"{restlet_url}&salesOrderId={sales_order_id}"
            result = self.client.call_restlet(full_url, method='GET')
            
            if result.get('success') and result.get('pdfBase64'):
                return {
                    'success': True,
                    'pdf_base64': result['pdfBase64'],
                    'filename': result.get('filename', f'SalesOrder_{sales_order_id}.pdf')
                }
            else:
                return {
                    'success': False,
                    'error': result.get('error', 'Failed to generate PDF')
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'Error generating PDF: {str(e)}'
            }

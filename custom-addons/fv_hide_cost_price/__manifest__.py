# -*- coding: utf-8 -*-
###############################################################################
#
#    Falcon Valley
#    Copyright (C) 2024-TODAY Falcon Valley (info@falcon-v.com)
#
#    This program is free software: you can modify
#    it under the terms of the GNU Affero General Public License (AGPL) as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
###############################################################################
{
    'name': 'FV Hide Cost Price',
    'version': '18.0.1.0.0',
    'category': 'Stock',
    'summary': 'Hide product cost price and valuation fields for specific users',
    'description': """
FV Hide Cost Price
==================
This module allows you to hide product cost price and stock valuation fields
from users who do not have the "View Cost Price" permission.

Features:
---------
* Hide Cost Price (Standard Price) field in product forms and lists
* Hide Unit Cost and Total Value columns in Stock Valuation Layer
* Hide Average Cost and Total Value columns in Stock Product list
* Control access through a dedicated security group "View Cost Price"

Usage:
------
1. Install the module
2. Go to Settings > Users & Companies > Groups
3. Find "View Cost Price" group
4. Add users who should be able to see cost prices to this group
5. Users not in this group will not see any cost-related fields

Price: Free
    """,
    'author': 'Falcon Valley',
    'company': 'Falcon Valley',
    'maintainer': 'Falcon Valley',
    'website': 'https://falcon-v.com',
    'support': 'info@falcon-v.com',
    'depends': ['product', 'stock_account'],
    'license': 'AGPL-3',
    'price': 0.0,
    'currency': 'USD',
    'data': [
        'security/fv_hide_cost_price_groups.xml',
        'views/product_product_views.xml',
        'views/product_template_views.xml'
    ],
    'images': ['static/description/banner.jpg'],
    'installable': True,
    'auto_install': False,
    'application': False,
}

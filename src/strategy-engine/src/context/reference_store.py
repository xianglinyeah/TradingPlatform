"""
ReferenceStore for slow-changing reference data.

Future extensions:
- Fundamental data (PE, ROE, etc.)
- Money flow data
- Industry classification
- Index components
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ReferenceStore:
    """
    Slow-changing reference data. Currently a stub implementation.

    Future extensions:
    - get_fundamental()  Fundamental data (PE, ROE, etc.)
    - get_money_flow()   Money flow data
    - get_industry()     Industry classification
    - get_index_components()  Index constituents
    """

    def get_fundamental(self, symbol: str) -> Optional[dict]:
        return None

    def get_money_flow(self, symbol: str) -> Optional[dict]:
        return None

    def get_industry(self, symbol: str) -> Optional[str]:
        return None

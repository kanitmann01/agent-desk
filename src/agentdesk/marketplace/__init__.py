"""The plugin marketplace: catalog assembly, enterprise policy, JSON API.

T4 owns this package. The server delegates every /api/marketplace/ path
here after its normal session and Origin gates have already run.
"""

from . import api, catalog, policy

__all__ = ["api", "catalog", "policy"]

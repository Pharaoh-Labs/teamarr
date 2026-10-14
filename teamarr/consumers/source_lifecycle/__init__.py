"""Source lifecycle: discover, add, retire, remove (#1058).

Two passes read one policy (``policy.load_policy``):

* the daily pass (``discovery.run_discovery_scan``): scan M3U groups that
  are not sources, re-add approved ones, add automatically for toggled
  leagues, retire and bring back discovered sources;
* the per-generation pass (``missing.detect_stale_groups``): mark sources
  whose Dispatcharr group is gone and delete the ones the policy says to.

The UI for all of it is the Automation section of the Sources page.
"""

from .discovery import discovery_status, run_discovery_scan
from .missing import detect_stale_groups
from .policy import SourceLifecyclePolicy, load_policy

__all__ = [
    "SourceLifecyclePolicy",
    "detect_stale_groups",
    "discovery_status",
    "load_policy",
    "run_discovery_scan",
]

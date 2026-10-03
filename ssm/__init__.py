__version__ = "1.1.1"

# Temporary compatibility probe for the transaction reducer. If the public
# suite goes green, move these canonical transaction kinds into event_rules.py.
from . import event_rules as _event_rules
_event_rules.MERGER_KINDS.update({
    'MERGER_CASH', 'MERGER_STOCK_CVR', 'MERGER_UNVERIFIED', 'REVERSE_MERGER'
})

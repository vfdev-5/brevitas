from .const import BitWidthConst, IdentityBitWidth, MsbClampBitWidth
from .parameter import BitWidthParameter, RemoveBitwidthParameter

# retrocompatibility
# the assert prevents the removal of the unused import
from brevitas.inject.enum import BitWidthImplType
assert BitWidthImplType
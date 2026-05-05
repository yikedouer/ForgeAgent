"""工具实现——导入时自动注册。"""

# 导入每个模块会触发 @instrument() 注册
from . import shell     # noqa: F401
from . import reader    # noqa: F401
from . import writer    # noqa: F401
from . import editor    # noqa: F401
from . import finder    # noqa: F401
from . import agent     # noqa: F401
from . import team      # noqa: F401
from . import skill     # noqa: F401
from . import memory    # noqa: F401

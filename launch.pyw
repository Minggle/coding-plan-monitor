"""开机自启启动器：以绝对路径被 pythonw 调用，不依赖工作目录。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import main

if __name__ == "__main__":
    main()

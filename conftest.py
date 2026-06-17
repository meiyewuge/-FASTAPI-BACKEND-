import sys
import os
# 将项目根目录加入 sys.path，使 tests/ 能 import backend.app.*
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

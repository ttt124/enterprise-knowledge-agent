"""从仓库根目录运行，无需安装包或修改系统 PYTHONPATH。"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from knowledge_agent.cli import main


if __name__ == "__main__":
    sys.exit(main())

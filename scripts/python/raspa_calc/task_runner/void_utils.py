import pandas as pd

from .csv_utils import read_csv_with_fallbacks
from .logging_utils import logger


def load_void_fraction_from_csv(csv_path, framework_column, void_column):
    """Load void fraction mapping from CSV."""
    try:
        df = read_csv_with_fallbacks(csv_path)

        if framework_column not in df.columns:
            logger.error(f"CSV文件中未找到框架列: {framework_column}")
            return {}

        if void_column not in df.columns:
            logger.error(f"CSV文件中未找到孔隙率列: {void_column}")
            return {}

        void_dict = {}
        for _, row in df.iterrows():
            framework = row[framework_column]
            void_frac = row[void_column]
            if pd.notna(framework) and pd.notna(void_frac):
                void_dict[str(framework)] = float(void_frac)

        logger.info(f"从CSV文件加载了 {len(void_dict)} 个框架的孔隙率数据")
        return void_dict

    except Exception as e:
        logger.error(f"加载孔隙率数据失败: {e}")
        return {}

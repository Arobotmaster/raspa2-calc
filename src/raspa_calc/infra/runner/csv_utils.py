import pandas as pd


def read_csv_with_fallbacks(csv_path, encodings=None):
    encodings = encodings or ("utf-8-sig", "utf-8", "gbk")
    last_error = None
    for enc in encodings:
        try:
            return pd.read_csv(csv_path, encoding=enc)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return pd.read_csv(csv_path)

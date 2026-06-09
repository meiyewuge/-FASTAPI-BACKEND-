"""7 大库 library_ref 静态映射（补丁说明：V0.1.3 为静态映射，V0.1.4 替换为 RAG 检索）。

来源：《后端开发文档》第 6.1 节 ISSUE_LIBRARY_MAP，9 类问题 → 7 大库条目编号。
"""

ISSUE_LIBRARY_MAP = {
    "traffic": {
        "lib1": ["K-DZ-01-M01", "K-DZ-01-M03"],
        "lib2": ["K-DZ-02-P01-001", "-002", "-003", "-004", "-005"],
        "lib3": ["K-DZ-03-RC02"],
        "lib4": ["K-DZ-04-A01"],
        "lib5": ["K-DZ-05-D01", "K-DZ-05-D06"],
    },
    "deal": {
        "lib1": ["K-DZ-01-M04", "K-DZ-01-M05"],
        "lib2": ["K-DZ-02-P02-001~005", "K-DZ-02-P04-001~004"],
        "lib3": ["K-DZ-03-RC03", "K-DZ-03-RC05"],
        "lib4": ["K-DZ-04-A02", "K-DZ-04-A04"],
        "lib6": ["K-DZ-06-E03"],
        "lib7": ["K-DZ-07-S01", "K-DZ-07-S07"],
    },
    "new_customer": {
        "lib1": ["K-DZ-01-M03", "K-DZ-01-M04"],
        "lib2": ["K-DZ-02-P02-001", "K-DZ-02-P02-003"],
        "lib3": ["K-DZ-03-RC03"],
        "lib4": ["K-DZ-04-A02"],
        "lib6": ["K-DZ-06-E01", "K-DZ-06-E03"],
        "lib7": ["K-DZ-07-S01"],
    },
    "price": {
        "lib1": ["K-DZ-01-M05"],
        "lib2": ["K-DZ-02-P04-001~004"],
        "lib3": ["K-DZ-03-RC05"],
        "lib4": ["K-DZ-04-A04"],
        "lib5": ["K-DZ-05-D04"],
        "lib7": ["K-DZ-07-S04"],
    },
    "lock": {
        "lib1": ["K-DZ-01-M09"],
        "lib2": ["K-DZ-02-P03"],
        "lib3": ["K-DZ-03-RC04"],
        "lib4": ["K-DZ-04-A03"],
        "lib7": ["K-DZ-07-S03"],
    },
    "repeat": {
        "lib1": ["K-DZ-01-M07", "K-DZ-01-M08", "K-DZ-01-M09"],
        "lib2": ["K-DZ-02-P03-001~005"],
        "lib3": ["K-DZ-03-RC04"],
        "lib4": ["K-DZ-04-A03"],
        "lib7": ["K-DZ-07-S02", "K-DZ-07-S03", "K-DZ-07-S05"],
    },
    "project": {
        "lib2": ["K-DZ-02-P06-001~004"],
        "lib4": ["K-DZ-04-A06"],
        "lib5": ["K-DZ-05-D04"],
    },
    "staff": {
        "lib1": ["K-DZ-01-M15"],
        "lib2": ["K-DZ-02-P05-001~004"],
        "lib3": ["K-DZ-03-RC06"],
        "lib4": ["K-DZ-04-A05"],
        "lib6": ["K-DZ-06-E01", "-E02", "-E03", "-E04", "-E05"],
    },
    "risk": {
        "lib1": ["K-DZ-01-M11", "-M12", "-M13", "-M14"],
        "lib3": ["K-DZ-03-RC07"],
        "lib4": ["K-DZ-04-A02"],
        "lib6": ["K-DZ-06-E02", "-E03"],
    },
}


def get_library_ref(issue_type: str) -> dict:
    """返回某问题类型的 7 大库映射；未知类型返回空 dict。"""
    return ISSUE_LIBRARY_MAP.get(issue_type, {})

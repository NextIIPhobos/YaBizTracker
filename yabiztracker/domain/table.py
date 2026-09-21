from enum import IntEnum


class OrgColumn(IntEnum):
    """Stable column contract shared by the organization table and its actions."""

    NAME = 0
    ADDRESS = 1
    SETTLEMENT = 2
    CATEGORY = 3
    APPEARED_DATE = 4
    AGE = 5
    PHONE = 6
    EMAIL = 7
    WEBSITE = 8
    SOCIAL = 9
    STATUS = 10
    COMMENT = 11
    RESPONSIBLE = 12
    NEXT_CONTACT = 13
    SCORE = 14

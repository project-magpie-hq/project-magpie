from enum import StrEnum


class NodeNames(StrEnum):
    OWL_DIRECTOR = "owl_director"
    OWL_TOOLS = "owl_tools"
    HAWK_PICKER = "hawk_picker"
    HAWK_TOOLS = "hawk_tools"
    MEERKAT_SCANNER = "meerkat_scanner"
    # Calculate Team (Bull/Bear/Dolphin 토론 서브그래프)
    CALCULATE_TEAM = "calculate_team"
    CALCULATE_TEAM_TOOLS = "calculate_team_tools"

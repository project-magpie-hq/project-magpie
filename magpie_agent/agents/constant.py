from enum import StrEnum


class NodeNames(StrEnum):
    OWL_DIRECTOR = "owl_director"
    OWL_TOOLS = "owl_tools"
    FOX_FINDER = "fox_finder"
    FOX_TOOLS = "fox_tools"
    HAWK_PICKER = "hawk_picker"
    HAWK_TOOLS = "hawk_tools"
    MEERKAT_SCANNER = "meerkat_scanner"
    # Calculate Team (Bull/Bear/Dolphin 토론 서브그래프)
    CALCULATE_TEAM = "calculate_team"
    CALCULATE_TEAM_TOOLS = "calculate_team_tools"
    # Analyze & Calculate 서브그래프 (Meerkat → Calculate Team)
    ANALYZE_AND_CALCULATE = "analyze_and_calculate"
    # Parallel Coordinator (per-coin 병렬 처리)
    PARALLEL_COORDINATOR = "parallel_coordinator"

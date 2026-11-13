from app.domain.schemas import EnergyHour, validate_day


def match_demand(rows: list[EnergyHour], target):
    return validate_day(rows, target)

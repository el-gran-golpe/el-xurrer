from datetime import datetime, timedelta


def get_closest_monday():
    """
    Get the closest Monday to today's date.
    If today is Monday, returns today.
    If today is Thursday or later, returns next Monday.
    If today is Tuesday or Wednesday, returns previous Monday.
    """
    today = datetime.now()
    weekday = today.weekday()  # Monday = 0, Sunday = 6

    if weekday == 0:  # If today is Monday
        return today
    elif weekday < 4:  # Tuesday (1), Wednesday (2), Thursday (3)
        # Return Monday of current week (go back to the most recent Monday)
        return today - timedelta(days=weekday)
    else:  # Friday (4), Saturday (5), Sunday (6)
        # Return next Monday (go forward to the upcoming Monday)
        return today + timedelta(days=(7 - weekday))
